# LiFi
Networking over QR Code

## Introduction
Use a stream of QR codes to transfer data from a Unix machine to a mobile. This is a weekend hack, adjust expectations accordingly.
The sender is a shell script which takes a file, chops it up into tiny pieces and displays each piece on the terminal for a brief interval.
The receiver is a static website which can be loaded on a mobile. Point it to the screen of the sender, and it will capture the chunks and assemble them into a downloadable file.

### Installation

The sender is assumed to be a Unix machine (Linux, MacOS). On the sender, install `qrencode` using the native package manager - `yum`, `apt`, `brew` as applicable.
The receiver is a website (no cookies, no analytics JS, no nothing) and trivially self-hostable. A sample receiver is hosted at https://ganeshv.github.io/lifi/

### Usage

To send, login to the machine containing the file from the terminal. Run

```
bash lifi-sender.sh [-c <chunksize>] [-f <fps>] [-r <repeat>] <filename>
```

`fps` controls how many QR codes are displayed per second. May need to reduce it for remote logins.
`repeat` controls how many times the file is repeated. Sometimes the receiver skips a frame because of terminal glitches, and repeating ensures that the missing frame is caught the next time round. The correct way to do this is using fountain codes, out of scope for a weekend project.

Reduce the font size and increase the terminal size to the point that the entire QR code is visible.

A sample receiver is hosted at https://ganeshv.github.io/lifi/ - load the page on a mobile, hit "Scan". Once all the chunks have been captured, the "Download" button turns green, and the captured file can be downloaded to the mobile.

Transfer rates are slow, about 3-4KB per second. It is possible to improve FPS using a GUI rather than a terminal, and denser/colour based QR codes, but again, out of scope for now.

## TCP/IP over QR

Point-to-point TCP/IP communication between two (laptop) computers with
cameras and screens facing each other. IP packets are encoded as QR codes
and flashed on the screen of the sending peer, and captured and decoded
by the camera of the receiving peer.

A TUN interface (utun on MacOS) is used to implement the "QR Ethernet"
NIC.

Little practical value but good fun.

There is a tradeoff between MTU, distance between two camera/screen pairs
and reliability.

Implemented in `lifi-ppp.py`.
