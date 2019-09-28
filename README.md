# Bittorrent Implemation in Python

#### Contributors: Zhanyi Tan, Jiawei Shi, Boxuan Zhu, Youming Zhang

#### Features:
1. Bencode: 
  - decode and encode a torrent file into readable format. This file provide different tearser format.
  - Meta info will be provide all the data have being bencoded.
2. HTTP request and response: 
  - Using HTTP protocol request funstionality to make http request to tracker and receive response from tracker with a list of peers. 
3. Piece Managment: 
  - Check what piece to request based on piece information given. 
  - Check bit map sent from peer and update rarest piece. 
  - Write the piece to disk once all block arrived and checksum is expected.
4. Bittorrent Protocol:
  - Conncet to other peers through TCP and allow other peers connect by listening to certain ports
  - Encode messages into handshake, choke, unchoke, interested, not interested, have, bitfield, request, piece, and cancel messages according to the official document.

#### Usage
