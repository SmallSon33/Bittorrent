import asyncio
import logging
import math
import os
import time
import pieceManager
from asyncio import Queue
from collections import namedtuple
from hashlib import sha1

from protocol import PeerConnection, REQ_SIZE
from tracker import Tracker
from pieceManager import PieceManager


MAX_CONNECT = 40 # 40 downlaod, 20 seed
SERVER_TUPLE = ('0', 0)

class TorrentClient:

    def __init__(self, torrent):
        self.tracker = Tracker(torrent)
        # The list of potential peers is the work queue, consumed by the
        # PeerConnections
        self.free_peers = Queue()
        # The list of peers is the list of workers that *might* be connected
        # to a peer. Else they are waiting to consume new remote peers from
        # the `free_peers` queue. These are our workers!
        self.peers = []
        # The piece manager implements the strategy on which pieces to
        # request, as well as the logic to persist received pieces to disk.
        self.piece_manager = PieceManager(torrent)
        self.abort = False

    async def start(self):
        """
        Start downloading the torrent held by this client.
        This results in connecting to the tracker to retrieve the list of
        peers to communicate with. Once the torrent is fully downloaded or
        if the download is aborted this method will complete.
        """
        self.peers = []
        for _ in range(MAX_CONNECT):
            NewPeer = PeerConnection(self.free_peers,
                                     self.tracker.torrent.info_hash,
                                     self.tracker.peer_id,
                                     self.piece_manager,
                                     self._on_block_retrieved)
            self.peers.append(NewPeer)

        asyncio.start_server(self.start_seeder_connection, '127.0.0.1', 6889)
        # The time we last made an announce call (timestamp)
        previous = None
        # Default interval between announce calls (in seconds)
        interval = 20*60
        print('start downloading')
        while True:
            if self.abort:
                print ('Abort downloading')
                break

            if self.piece_manager.complete:
                print ('Finish downloading')
                print(self.piece_manager.get_bitfield())

            current = time.time()
            if (not previous) or (previous + interval < current):
                response = await self.tracker.connect(
                    first=previous if previous else False,
                    uploaded=self.piece_manager.bytes_uploaded,
                    downloaded=self.piece_manager.bytes_downloaded)

                if response:
                    previous = current
                    interval = response.interval
                    while not self.free_peers.empty():
                        self.free_peers.get(False)
                    try:
                        for peer in response.peers:
                            print('peers ' + str(peer))
                            self.free_peers.put_nowait(peer)
                    except Exception as e:
                        logging.warning('no peer is replied from tracker')
            else:
                await asyncio.sleep(3)


            #Stop the download or seeding process.
    async def stop(self):
        self.abort = True
        for peer in self.peers:
            peer.stop()
        self.piece_manager.close()
        await self.tracker.close()

    async def start_seeder_connection(self, reader, writer):
        NewServer = PeerConnection(self.free_peers,
                                 self.tracker.torrent.info_hash,
                                 self.tracker.peer_id,
                                 self.piece_manager,
                                 self._on_block_retrieved, True)
        await NewServer.init_server(reader, writer)

    def _on_block_retrieved(self, peer_id, piece_index, block_offset, data):
        """
        Callback function called by the `PeerConnection` when a block is
        retrieved from a peer.
        :param peer_id: The id of the peer the block was retrieved from
        :param piece_index: The piece index this block is a part of
        :param block_offset: The block offset within its piece
        :param data: The binary data retrieved
        """
        self.piece_manager.block_received(
            peer_id=peer_id, piece_index=piece_index,
            block_offset=block_offset, data=data)
