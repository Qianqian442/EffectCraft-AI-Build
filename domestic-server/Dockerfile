FROM node:22-bookworm-slim
WORKDIR /srv/effectcraft
COPY package*.json ./
RUN npm ci --omit=dev
COPY src ./src
ENV NODE_ENV=production PORT=8788
EXPOSE 8788
USER node
CMD ["node", "src/server.js"]
