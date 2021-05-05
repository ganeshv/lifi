"""
LiFi - IP over QR Code

Point-to-point TCP/IP communication between two (laptop) computers with
cameras and screens facing each other. IP packets are encoded as QR codes
and flashed on the screen of the sending peer, and captured and decoded
by the camera of the receiving peer.

A TUN interface (utun on MacOS) is used to implement the "QR Ethernet"
NIC.

Little practical value but good fun.

There is a tradeoff between MTU, distance between two camera/screen pairs
and reliability.
"""

# TODO
# Linux support

import sys
import os
import socket
import fcntl
import struct
import subprocess
import argparse
import time
import qrcode
from pyzbar import pyzbar
import cv2 as cv
import numpy
import select
import base64

LIFI_V1_HDR = '!3sBIIH'
LIFI_V1_HDR_SIZE = 14
LIFI_V1_TAIL_SIZE = 4
LIFI_FRAME_SIZE = LIFI_V1_HDR_SIZE + LIFI_V1_TAIL_SIZE
AF_INET_HDR = b'\x00\x00\x00\x02'

def main(opts):
    sock = macos_utun(opts)
    sock.setblocking(False)
    eventloop(opts, sock)

def eventloop(opts, sock):
    """
    Main event loop. We capture camera frames as fast as we can, decode packets and
    push them into the socket as soon as it is writable.

    Data coming from the socket is converted to a QR code and displayed for at least
    1/fps seconds to give the receiver a chance to capture it.
    """

    # Packet queues
    send_queue = []
    recv_queue = []
    frame_mtu = opts.mtu + LIFI_FRAME_SIZE + 4

    last = time.perf_counter()
    fps_interval = 1 / opts.fps

    # We display a white frame when no packet is being transmitted.
    # This reduces overhead for the peer.
    white_frame = numpy.zeros((opts.width, opts.width, 3), numpy.uint8)
    white_frame[:] = (255, 255, 255)

    cap = cv.VideoCapture(0)
    if not cap.isOpened():
        print("Cannot open camera")
        exit()

    # Half hearted attempt to move the QR code window to 0,0
    # but you'll have to move it manually and raise it anyway.
    cv.namedWindow('qr')
    cv.moveWindow('qr', 0, 0)
    cv.resizeWindow('qr', opts.width, opts.width)

    last_packet = None
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Can't receive frame (stream end?). Exiting ...")
            break
        img = resize_w(frame, width=1024)
        qrcodes = pyzbar.decode(img)
        for q in qrcodes:
            packet = lifi_unwrap(opts, q.data)
            if packet is not None and packet != last_packet:
                last_packet = packet
                recv_queue.append(packet)

        readable, writable, err = select.select([sock], [sock], [sock], 0)
        if readable:
            p = sock.recv(frame_mtu)
            if len(p) == 0:
                raise Exception('utun socket closed')
            if p[0:4] != AF_INET_HDR:
                debug_print(opts, 'received non-AF_INET packet')
            else:
                send_queue.append(p[4:])

        if writable and len(recv_queue):
            p = recv_queue.pop(0)
            sent = sock.send(AF_INET_HDR + p)
            if sent == 0:
                raise Exception('utun socket closed')
            if sent < len(p):
                raise Exception('short write to utun, had %d wrote %d' % (len(p), sent))

        if time.perf_counter() - last > fps_interval:
            if len(send_queue):
                out_packet = send_queue.pop(0)
                qr_show(opts, out_packet)
            else:
                cv.imshow('qr', white_frame)
            last = time.perf_counter()

        cv.imshow('frame', img)
        if cv.waitKey(1) == ord('q'):
            break

    # When everything done, release the capture
    cap.release()
    cv.destroyAllWindows()

def qr_show(opts, packet):
    if len(packet) > opts.mtu:
        raise Exception('Invalid out_packet length %d' % len(packet))
    lifi_packet = lifi_wrap(opts, packet)
    if opts.base64:
        out_packet = base64.b64encode(lifi_packet)
    else:
        out_packet = lifi_packet
    debug_print(opts, 'qr out packet', len(out_packet), len(lifi_packet), len(out_packet))
    qr_img = qrcode.make(out_packet)
    cv_qr_img = numpy.array(qr_img.get_image().resize((opts.width, opts.width)).convert('L'))
    print(qr_img.get_image().size)
    cv.imshow('qr', cv_qr_img)

LIFI_V1_HDR = '!3sBIIH'
LIFI_V1_HDR_SIZE = 14

def lifi_wrap(opts, packet):
    """
    Encapsulate IP packet in lifi v1 frame. 14 bytes header
    Offset
    0:      LIF\\x1 # LIFI version 1
    4:      Destination IP
    8:      Source IP
    12:     2 bytes packet type
    14:     IP packet of n bytes (68 < n <= 1500)
    14 + n: padding of 0s to offset IP MTU + 14
    MTU + 14:   4 bytes trailer, reserved

    IP packet will be padded so the LiFi packet is a fixed size

    Packet types:
    0x800:  IPv4

    In future there will be a pairing mechanism to encrypt IP
    packets, key exchange will use a different packet type.
    """

    lip = opts.local_ip
    rip = opts.remote_ip
    out = struct.pack(LIFI_V1_HDR, 'LIF'.encode(), 1, opts.remote_ip,
        opts.local_ip, 0x800) # LIFI header
    out += packet # IP payload
    out += (opts.mtu - len(packet)) * b'\x00' #padding
    out += b'\x00\x00\x00\x00' # LIFI trailer

    return out

def lifi_unwrap(opts, p, reflect=False):
    """
    Unwrap and validate lifi packet, return IP packet or None.
    """

    IPv4_HDR = '!BBHHHBBH4s4s'
    IPv4_HDR_SIZE = 20

    try:
        packet = base64.b64decode(p, validate=True)
    except:
        packet = p

    if len(packet) != LIFI_V1_HDR_SIZE + opts.mtu + 4:
        debug_print(opts, 'short packet', len(packet))
        return None

    magic, version, dest_ip, src_ip, packet_type = struct.unpack(LIFI_V1_HDR, packet[:LIFI_V1_HDR_SIZE])

    if magic != 'LIF'.encode() or version != 1:
        debug_print(opts, 'received packet not a supported LIF packet')
        return None

    if dest_ip != opts.local_ip and not reflect:
        debug_print(opts, 'received packet not destined for us %x' % dest_ip)
        return None
    if src_ip != opts.remote_ip and not reflect:
        debug_print(opts, 'received packet not from our peer %x' % src_ip)
        return None
    if packet_type & 0xfff != 0x800:
        debug_print(opts, 'received packet not IP')
        return None

    ip_packet = packet[LIFI_V1_HDR_SIZE:]
    ip_header = struct.unpack(IPv4_HDR, ip_packet[:IPv4_HDR_SIZE])
    ip_size = ip_header[2]

    return ip_packet[:ip_size]


def macos_utun(opts):
    """
    Open utun1 interface and return the socket. Must be run with root privileges.
    """

    UTUN_CONTROL_NAME = 'com.apple.net.utun_control'.encode()
    CTLIOCGINFO = 3227799043
    MAX_KCTL_NAME = 96
    CTL_STRUCT = '<I%ds' % MAX_KCTL_NAME
    UTUN_DEV = 1
    
    sock = socket.socket(socket.PF_SYSTEM, socket.SOCK_DGRAM, socket.SYSPROTO_CONTROL)
    ci = struct.pack(CTL_STRUCT, 0, UTUN_CONTROL_NAME)
    ctl_info = fcntl.ioctl(sock, CTLIOCGINFO, ci)
    ctl_id, ctl_name = struct.unpack(CTL_STRUCT, ctl_info)
    sock.connect((ctl_id, UTUN_DEV + 1))
    ret = subprocess.run(['ifconfig', 'utun%d' % UTUN_DEV, opts.local, opts.remote, 'mtu', str(opts.mtu)])
    if ret.returncode:
        print('ifconfig failed: ', ret.stderr)
        sys.exit(1)

    return sock

def resize_w(frame, width=400):
    """
    Resize to width pixels, preserving aspect ratio
    """

    scale = width / frame.shape[1]
    nsize = (width, int(frame.shape[0] * scale))
    return cv.resize(frame, nsize, interpolation=cv.INTER_AREA)

def validate_ip(opts, name):
    try:
        ip = getattr(opts, name)
        parts = ip.split('.')
        parts = [int(p) for p in parts]
        if len(parts) == 4 and all(p >= 0 and p < 256 for p in parts):
            setattr(opts, name + '_ip', (parts[0] << 24) + (parts[1] << 16) + (parts[2] << 8) + parts[3])
            return
    except:
        pass
    print('Invalid %s IP: %s' % (name, ip))

def debug_print(opts, *args, **kwargs):
    if opts.debug:
        print(*args, **kwargs)

def process_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', help='verbose debugging', action='store_true')
    parser.add_argument('--fps', type=int, default=10)
    parser.add_argument('-w', '--width', type=int, default=800, help='width of QR code window')
    parser.add_argument('-m', '--mtu', help='MTU should be between 68 and 1500', type=int, default=400)
    parser.add_argument('-l', '--local', type=str, help='local IP', required=True)
    parser.add_argument('-r', '--remote', type=str, help='remote IP', required=True)
    opts = parser.parse_args()

    if opts.mtu > 1500 or opts.mtu < 68:
        print('MTU should be between 68 and 1500')
        sys.exit(1)

    # XXX base64 encode everything due to pyzbar bug
    opts.base64 = True

    validate_ip(opts, 'local')
    validate_ip(opts, 'remote')

    return opts

if __name__ == '__main__':
    n = process_args()
    main(n)
