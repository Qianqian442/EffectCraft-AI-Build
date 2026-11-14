module github.com/Diniboy1123/usque/mobileandroid

go 1.26.3

require (
	github.com/Diniboy1123/usque v0.0.0
	golang.org/x/mobile v0.0.0-20261011034528-197770444867
)

tool golang.org/x/mobile/cmd/gobind

replace github.com/Diniboy1123/usque => ./upstream-usque
