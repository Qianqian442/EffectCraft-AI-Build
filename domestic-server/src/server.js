import express from "express";
import http from "node:http";
import crypto from "node:crypto";
import fs from "node:fs";
import pg from "pg";
import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import { WebSocketServer, WebSocket } from "ws";

const { Pool } = pg;
const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "3.1mb" }));
const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 20 });
const JWT_SECRET = process.env.JWT_SECRET || "";
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "";
if (JWT_SECRET.length < 32 || ADMIN_PASSWORD.length < 12) throw new Error("JWT_SECRET至少32位，ADMIN_PASSWORD至少12位");
const NO_QQ = "__effectcraft_no_qq__:";
const NO_WECHAT = "__effectcraft_no_wechat__:";
const accountSockets = new Map();
const nodeSockets = new Map();
const fail = (res, status, message, extra = {}) => res.status(status).json({ detail: { message, ...extra } });
const publicUser = (r) => ({ id:r.id, qq:String(r.qq||"").startsWith(NO_QQ)?"":r.qq, wechat:String(r.wechat||"").startsWith(NO_WECHAT)?"":r.wechat, name:r.name, avatar_url:r.avatar_url||"", created_at:r.created_at, banned_until:r.banned_until||null, ban_reason:r.ban_reason||"" });
const tokenFor = (sub, role, seconds, device_id=null) => jwt.sign({ sub, role, ...(device_id?{device_id}:{}) }, JWT_SECRET, { expiresIn:seconds });
function claims(req, role) {
  const h=req.headers.authorization||"";
  if(!h.startsWith("Bearer ")) throw Object.assign(new Error("需要登录"),{status:401});
  const c=jwt.verify(h.slice(7),JWT_SECRET);
  if(c.role!==role) throw Object.assign(new Error("无权访问"),{status:401});
  return c;
}
async function activeAccount(id) {
  const row=(await pool.query("SELECT * FROM accounts WHERE id=$1",[id])).rows[0];
  if(!row) throw Object.assign(new Error("账号不存在，请重新登录"),{status:401});
  if(row.banned_until && new Date(row.banned_until).getTime()>Date.now()) throw Object.assign(new Error("账号已被管理员封禁"),{status:423,until:row.banned_until,reason:row.ban_reason});
  if(row.banned_until) await pool.query("UPDATE accounts SET banned_until=NULL,ban_reason='' WHERE id=$1",[id]);
  return row;
}
function validAvatar(v) {
  if(!v)return true;
  if(/^https?:\/\/\S+$/i.test(v))return true;
  return /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/i.test(v)&&v.length<=2900000;
}
function sendAccount(id,event){for(const ws of accountSockets.get(id)||[])if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(event));}
function sendNodes(event){for(const ws of nodeSockets.values())if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(event));}
async function getNetwork(){return (await pool.query("SELECT enabled,changed_at,changed_by FROM network_state WHERE id=1")).rows[0]||{enabled:true,changed_by:"bootstrap"};}
async function requireAdmin(req){return claims(req,"admin");}
app.get("/health",async(_req,res)=>{try{await pool.query("SELECT 1");res.json({ok:true,service:"EffectCraft Domestic Account API",database:true});}catch{res.status(503).json({ok:false,database:false});}});
app.post("/v1/register",async(req,res)=>{try{
 const b=req.body||{},qq=String(b.qq||"").trim(),wechat=String(b.wechat||"").trim(),name=String(b.name||"").trim(),password=String(b.password||""),avatar=String(b.avatar_url||"").trim();
 if(!qq&&!wechat)return fail(res,422,"QQ号和微信号至少填写一项");
 if(qq&&!/^[1-9][0-9]{4,11}$/.test(qq))return fail(res,422,"QQ号应填写5至12位数字");
 if(wechat&&!/^[A-Za-z][A-Za-z0-9_-]{5,31}$/.test(wechat))return fail(res,422,"微信号格式不正确");
 if(!name||name.length>40)return fail(res,422,"姓名不能为空且不能超过40字");
 if(password.length<8||password.length>128)return fail(res,422,"密码至少8位");
 if(!validAvatar(avatar))return fail(res,422,"头像必须是PNG/JPG/WebP图片或有效HTTPS地址，图片不能超过2MB");
 const id=crypto.randomUUID(),hash=await bcrypt.hash(password,12);
 await pool.query("INSERT INTO accounts(id,qq,wechat,name,password_hash,avatar_url) VALUES($1,$2,$3,$4,$5,$6)",[id,qq||NO_QQ+id,wechat||NO_WECHAT+id,name,hash,avatar]);
 const row=(await pool.query("SELECT * FROM accounts WHERE id=$1",[id])).rows[0];
 res.status(201).json({token:tokenFor(id,"user",30*86400),expires_in:30*86400,user:publicUser(row)});
 }catch(e){if(e.code==="23505")return fail(res,409,"名字、QQ号或微信号已被注册");console.error(e);fail(res,500,"服务器暂时无法处理请求");}});
app.post("/v1/login",async(req,res)=>{try{
 const id=String(req.body?.identifier||"").trim(),pw=String(req.body?.password||"");
 if(!id||!pw)return fail(res,422,"请填写QQ号/微信号和密码");
 const row=(await pool.query("SELECT * FROM accounts WHERE qq=$1 OR lower(wechat)=lower($1) LIMIT 1",[id])).rows[0];
 if(!row||!(await bcrypt.compare(pw,row.password_hash)))return fail(res,401,"QQ号/微信号或密码错误");
 await activeAccount(row.id);res.json({token:tokenFor(row.id,"user",30*86400),expires_in:30*86400,user:publicUser(row)});
 }catch(e){fail(res,e.status||500,e.message||"服务器错误",{until:e.until,reason:e.reason});}});
app.get("/v1/me",async(req,res)=>{try{const c=claims(req,"user"),row=await activeAccount(c.sub);res.json({user:publicUser(row)});}catch(e){fail(res,e.status||401,e.message||"登录已过期",{until:e.until,reason:e.reason});}});
app.post("/v1/profile",async(req,res)=>{try{
 const c=claims(req,"user"),b=req.body||{},row=await activeAccount(c.sub),qq=String(b.qq||"").trim(),wechat=String(b.wechat||"").trim(),name=String(b.name||"").trim(),avatar=String(b.avatar_url||"").trim();
 if((!qq&&!wechat)||(qq&&!/^[1-9][0-9]{4,11}$/.test(qq))||(wechat&&!/^[A-Za-z][A-Za-z0-9_-]{5,31}$/.test(wechat))||!name||name.length>40)return fail(res,422,"QQ号和微信号至少填写一项，且格式必须正确");
 if(!validAvatar(avatar))return fail(res,422,"头像格式不正确");
 let hash=row.password_hash;
 if(b.new_password){if(String(b.new_password).length<8||String(b.new_password).length>128)return fail(res,422,"新密码至少8位");if(!(await bcrypt.compare(String(b.current_password||""),hash)))return fail(res,401,"当前密码不正确");hash=await bcrypt.hash(String(b.new_password),12);}
 await pool.query("UPDATE accounts SET qq=$1,wechat=$2,name=$3,avatar_url=$4,password_hash=$5 WHERE id=$6",[qq||NO_QQ+c.sub,wechat||NO_WECHAT+c.sub,name,avatar,hash,c.sub]);
 res.json({user:publicUser((await pool.query("SELECT * FROM accounts WHERE id=$1",[c.sub])).rows[0])});
 }catch(e){if(e.code==="23505")return fail(res,409,"名字、QQ号或微信号已被其他账号使用");fail(res,e.status||500,e.message||"服务器错误");}});
app.post("/v1/admin/login",async(req,res)=>{if(req.body?.username!=="admin"||req.body?.password!==ADMIN_PASSWORD)return fail(res,401,"管理员账号或密码错误");res.json({token:tokenFor("admin","admin",8*3600),expires_in:8*3600});});
app.post("/v1/admin/device/enroll",async(req,res)=>{try{const {device_id,public_key,password}=req.body||{};if(password!==ADMIN_PASSWORD)return fail(res,401,"管理员密码错误");if(!/^[A-Za-z0-9_-]{16,80}$/.test(String(device_id||""))||!public_key)return fail(res,422,"设备信息无效");await pool.query("DELETE FROM admin_devices");await pool.query("INSERT INTO admin_devices(device_id,public_key) VALUES($1,$2)",[device_id,public_key]);res.json({token:tokenFor("admin","admin",30*86400,device_id),expires_in:30*86400,device_bound:true});}catch{fail(res,500,"管理员设备绑定失败");}});
app.post("/v1/admin/device/challenge",async(req,res)=>{try{const id=String(req.body?.device_id||"");if(!/^[A-Za-z0-9_-]{16,80}$/.test(id))return fail(res,422,"设备编号无效");const row=(await pool.query("SELECT device_id FROM admin_devices WHERE device_id=$1",[id])).rows[0];if(!row)return fail(res,404,"这台手机尚未绑定");const nonce=crypto.randomBytes(32).toString("base64url");await pool.query("INSERT INTO admin_device_challenges(nonce,device_id,expires_at) VALUES($1,$2,$3)",[nonce,id,Date.now()+120000]);await pool.query("DELETE FROM admin_device_challenges WHERE expires_at<$1",[Date.now()]);res.json({challenge:nonce,expires_in:120});}catch{fail(res,500,"无法生成设备挑战");}});
app.post("/v1/admin/device/login",async(req,res)=>{try{const {device_id,challenge,signature}=req.body||{};const row=(await pool.query("SELECT d.public_key,c.expires_at FROM admin_devices d JOIN admin_device_challenges c ON c.device_id=d.device_id WHERE d.device_id=$1 AND c.nonce=$2",[device_id,challenge])).rows[0];if(!row||Number(row.expires_at)<Date.now())return fail(res,401,"登录挑战已过期，请重试");await pool.query("DELETE FROM admin_device_challenges WHERE nonce=$1",[challenge]);const key=crypto.createPublicKey({key:Buffer.from(row.public_key,"base64url"),format:"der",type:"spki"});if(!crypto.verify("RSA-SHA256",Buffer.from(challenge,"base64url"),key,Buffer.from(signature,"base64url")))return fail(res,401,"管理员设备身份验证失败");await pool.query("UPDATE admin_devices SET last_seen=NOW() WHERE device_id=$1",[device_id]);res.json({token:tokenFor("admin","admin",30*86400,device_id),expires_in:30*86400,device_bound:true});}catch{fail(res,401,"管理员设备登录失败");}});
app.get("/v1/admin/users",async(req,res)=>{try{await requireAdmin(req);const q=String(req.query.q||"").trim();const sql=q?"SELECT * FROM accounts WHERE qq ILIKE $1 OR wechat ILIKE $1 OR name ILIKE $1 ORDER BY created_at DESC LIMIT 500":"SELECT * FROM accounts ORDER BY created_at DESC LIMIT 500";const rows=(await pool.query(sql,q?["%"+q+"%"]:[])).rows;res.json({users:rows.map(publicUser)});}catch(e){fail(res,401,e.message||"无权访问");}});
app.get("/v1/admin/users/:id",async(req,res)=>{try{await requireAdmin(req);const row=(await pool.query("SELECT * FROM accounts WHERE id=$1",[req.params.id])).rows[0];if(!row)return fail(res,404,"账号不存在");res.json({user:publicUser(row)});}catch(e){fail(res,401,e.message);}});
app.post("/v1/admin/users/:id/ban",async(req,res)=>{try{
 await requireAdmin(req);const row=(await pool.query("SELECT * FROM accounts WHERE id=$1",[req.params.id])).rows[0];if(!row)return fail(res,404,"账号不存在");
 let status,bannedUntil=null;
 if(req.body?.banned_until==null||req.body?.banned_until===""){await pool.query("UPDATE accounts SET banned_until=NULL,ban_reason='' WHERE id=$1",[req.params.id]);status="unbanned";}
 else{const t=Date.parse(req.body.banned_until),reason=String(req.body.reason||"").trim();if(!Number.isFinite(t)||t<=Date.now())return fail(res,422,"封禁时间必须晚于当前时间");if(!reason||reason.length>200)return fail(res,422,"请填写封禁原因（最多200字）");bannedUntil=new Date(t).toISOString();await pool.query("UPDATE accounts SET banned_until=$1,ban_reason=$2 WHERE id=$3",[bannedUntil,reason,req.params.id]);status="banned";}
 if(status==="banned"){const ws=nodeSockets.get(req.params.id);if(ws){ws.close(4003,"account banned");nodeSockets.delete(req.params.id);}}
 sendAccount(req.params.id,{type:"account_status_changed",status,banned_until:bannedUntil,changed_at:new Date().toISOString()});
 const updated=(await pool.query("SELECT * FROM accounts WHERE id=$1",[req.params.id])).rows[0];res.json({user:publicUser(updated),notification_delivered:1,revoked_node_sessions:0});
 }catch(e){fail(res,401,e.message||"无权访问");}});
app.delete("/v1/admin/users/:id",async(req,res)=>{try{await requireAdmin(req);const row=(await pool.query("SELECT * FROM accounts WHERE id=$1",[req.params.id])).rows[0];if(!row)return fail(res,404,"账号不存在");if(!row.banned_until||new Date(row.banned_until).toISOString()!=="9999-12-31T23:59:59.000Z")return fail(res,409,"只能删除已永久封禁的账号；请先执行永久封禁");await pool.query("DELETE FROM accounts WHERE id=$1",[req.params.id]);res.json({deleted:true,id:req.params.id,released:{name:row.name,qq:row.qq,wechat:row.wechat}});}catch(e){fail(res,401,e.message||"无权访问");}});
app.get("/v1/admin/network",async(req,res)=>{try{await requireAdmin(req);res.json({network:await getNetwork()});}catch(e){fail(res,401,e.message);}});
app.post("/v1/admin/network",async(req,res)=>{try{const c=await requireAdmin(req);if(typeof req.body?.enabled!=="boolean")return fail(res,422,"enabled必须是布尔值");const enabled=req.body.enabled;const changed_at=new Date().toISOString();await pool.query("UPDATE network_state SET enabled=$1,changed_at=$2,changed_by=$3 WHERE id=1",[enabled,changed_at,c.sub]);if(!enabled){sendNodes({type:"network_state",enabled:false,changed_at,changed_by:c.sub});for(const ws of nodeSockets.values())ws.close(4001,"network disabled by administrator");nodeSockets.clear();}res.json({network:{enabled,changed_at,changed_by:c.sub},disconnected:enabled?0:nodeSockets.size});}catch(e){fail(res,401,e.message);}});
app.get("/v1/admin/network/nodes",async(req,res)=>{try{await requireAdmin(req);res.json({enabled:(await getNetwork()).enabled,nodes:[...nodeSockets.entries()].map(([node_id,ws])=>({node_id,connected:ws.readyState===WebSocket.OPEN}))});}catch(e){fail(res,401,e.message);}});
app.get("/v1/nodes/network",async(req,res)=>{try{const c=claims(req,"user");await activeAccount(c.sub);res.json({network:await getNetwork()});}catch(e){fail(res,e.status||401,e.message);}});
app.get("/v1/nodes/peers",async(req,res)=>{try{const c=claims(req,"user");await activeAccount(c.sub);res.json({enabled:(await getNetwork()).enabled,peers:[...nodeSockets.entries()].filter(([id,ws])=>id!==c.sub&&ws.readyState===WebSocket.OPEN).map(([node_id,ws])=>({node_id,peer_id:ws.peerId||null,addresses:[]}))});}catch(e){fail(res,e.status||401,e.message);}});
const server=http.createServer(app);
const wss=new WebSocketServer({noServer:true,maxPayload:50000});
server.on("upgrade",async(req,socket,head)=>{try{
 const url=new URL(req.url,"http://localhost");if(!["/v1/nodes/events","/v1/events"].includes(url.pathname)){socket.destroy();return;}
 const raw=String(req.headers.authorization||"");if(!raw.startsWith("Bearer "))throw new Error("token");
 const c=jwt.verify(raw.slice(7),JWT_SECRET);if(c.role!=="user")throw new Error("role");await activeAccount(c.sub);
 if(url.pathname==="/v1/nodes/events"&&!(await getNetwork()).enabled){socket.write("HTTP/1.1 423 Network Disabled\r\n\r\n");socket.destroy();return;}
 wss.handleUpgrade(req,socket,head,ws=>{
  if(url.pathname==="/v1/events"){if(!accountSockets.has(c.sub))accountSockets.set(c.sub,new Set());accountSockets.get(c.sub).add(ws);ws.on("close",()=>accountSockets.get(c.sub)?.delete(ws));return;}
  nodeSockets.set(c.sub,ws);ws.send(JSON.stringify({type:"network_state",enabled:true}));
  ws.on("message",rawMessage=>{try{const m=JSON.parse(String(rawMessage));
   if(m.type==="hello"&&m.v===1){const peer=String(m.peer_id||"");if(!/^[1-9A-HJ-NP-Za-km-z]{20,100}$/.test(peer)){ws.send(JSON.stringify({type:"error",code:"invalid_peer_announcement"}));return;}ws.peerId=peer;ws.send(JSON.stringify({type:"peer_list",peers:[...nodeSockets.keys()].filter(id=>id!==c.sub)}));for(const [id,peerWs] of nodeSockets)if(id!==c.sub&&peerWs.readyState===WebSocket.OPEN)peerWs.send(JSON.stringify({type:"peer_online",node_id:c.sub,peer_id:peer}));return;}
   if(m.type==="relay"&&m.v===1&&typeof m.to==="string"&&typeof m.ciphertext==="string"&&m.ciphertext.length>=16&&m.ciphertext.length<=40000){const target=nodeSockets.get(m.to);if(target?.readyState===WebSocket.OPEN)target.send(JSON.stringify({type:"relay",from:c.sub,message_id:String(m.message_id||"").slice(0,80),sent_at:Number(m.sent_at)||Date.now(),ciphertext:m.ciphertext}));}
  }catch{}});
  ws.on("close",()=>{if(nodeSockets.get(c.sub)===ws)nodeSockets.delete(c.sub);for(const peer of nodeSockets.values())if(peer.readyState===WebSocket.OPEN)peer.send(JSON.stringify({type:"peer_offline",node_id:c.sub}));});
 });
 }catch{socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");socket.destroy();}});
await pool.query(fs.readFileSync(new URL("../schema.sql",import.meta.url),"utf8"));
const port=Number(process.env.PORT||8788);
server.listen(port,"0.0.0.0",()=>console.log("EffectCraft domestic server listening on "+port));
