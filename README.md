# syncprojects-client
[![Build Status](https://0.0.0.0/api/badges/keaneokelley/syncprojects/status.svg)](https://0.0.0.0/keaneokelley/syncprojects)
`syncprojects-client` is a Python desktop application that interfaces with [syncprojects-web](https://github.com/k3an3/syncprojects-web). It handles synchronization of DAW project and audio files, using the cloud (S3) or other backends for storage. `syncprojects-client` can run on Windows, Mac, or Linux. That said, I am primarily a Linux developer, so the Windows/Mac build/installation processes leave a lot to be desired.

## Features
* From web interface, trigger cloud sync of one or more "songs" (song == DAW project)
* Basic version control and locking (centrally managed by `syncprojects-web`)
* Open song in DAW while requesting exclusive check-out so nobody else can make conflicting edits
* Upload .mp3/.wav previews of songs upon export 
* Automatic updates (Windows)

This version largely serves as a prototype, though the main components do work. I would eventually like to port the client to a new language to address performance/robustness.

It is very important to note that `syncprojects` is DAW-agnostic. There are some references to Cubase things since that's what we've been using. However, `syncprojects` doesn't really care, and is not aware of the format of any files it deals with. It should work with any DAW, or any type of files (possibly with some simple code changes to make it configurable).

## History
`syncprojects-client` began as a <100 line Python script some time in 2020, designed to synchronize Cubase projects between myself and a friend that I play music with. It originally used a SMB drive as the central storage location and ran in a Windows command prompt. By the 2.0 release, a web interface became the primary means to control things, and eventually S3 replaced SMB.

## Dev/user docs coming soon...
