module github.com/qianqian/effectcraft/warp-mobile

go 1.26.3

require (
	github.com/Diniboy1123/usque v0.0.0
	golang.org/x/mobile v0.0.0-20261011034528-197770444867
)

replace github.com/Diniboy1123/usque => ./upstream-usque

tool (
	golang.org/x/mobile/cmd/gobind
	golang.org/x/mobile/cmd/gomobile
)
