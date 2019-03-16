import asyncio
import logging
import math
import os
import time
import bitstring
import random
from block import Piece, Block
from hashlib import sha1
from protocol import REQ_SIZE
from collections import namedtuple

# The type used for keeping track of pending request that can be re-issued
PendingRequest = namedtuple('PendingRequest', ['block', 'added'])

class PieceManager:
    """
    The PieceManager is responsible for keeping track of all the available
    pieces for the connected peers as well as the pieces we have available for
    other peers.
    """
    def __init__(self, torrent):
        self.torrent = torrent
        self.fd = os.open(self.torrent.output_file,  os.O_RDWR | os.O_CREAT)

        self.peers = {}
        self.have_pieces = []
        self.max_pending_time = 200 * 1000
        self.missing_pieces = self._initiate()
        self.total_pieces = len(torrent.pieces)
        self.rarest_pieces = [0] * self.total_pieces
        self.pending_blocks = []
        self.ongoing_pieces = []

    def _initiate(self) -> [Piece]:
        """
        Pre-construct the list of pieces and blocks based on the number of
        pieces and request size for this torrent.
        """
        #Initiate the pending list which include information for all pieces
        torrent = self.torrent
        pieces = []
        total_pieces = len(torrent.pieces)
        num_std_blocks = math.ceil(torrent.piece_length / REQ_SIZE)

        # print('looking at torrent.pieces')
        # print(torrent.pieces)
        for index, hash_value in enumerate(torrent.pieces):
            if index != total_pieces - 1:
                    blocks = []
                    for offset in range(num_std_blocks):
                        blocks.append(Block(index, offset * REQ_SIZE, REQ_SIZE))
            else:
                # Reach the last pieces
                last_length = torrent.total_length % torrent.piece_length
                num_blocks = math.ceil(last_length / REQ_SIZE)
                blocks = []
                for offset in range(num_blocks):
                    blocks.append(Block(index, offset * REQ_SIZE, REQ_SIZE))

                if last_length % REQ_SIZE > 0:
                    blocks[-1].length = last_length % REQ_SIZE
            pos = index * self.torrent.piece_length
            os.lseek(self.fd, pos, os.SEEK_SET)
            text = os.read(self.fd, self.torrent.piece_length)
            hash_value_tmp = sha1(text).digest()
            if hash_value_tmp == hash_value:
                self.have_pieces.append(Piece(index, blocks, hash_value))
            else:
                pieces.append(Piece(index, blocks, hash_value))
        # print('looking at the returened pieces')
        # print(self.have_pieces)
        return pieces

    def close(self):
        #Close the openign file which is used by piece
        if self.fd:
            os.close(self.fd)

    @property
    def complete(self):
        #Make sure all the needed pieces all downloaded
        return len(self.have_pieces) == self.total_pieces

    @property
    def bytes_downloaded(self) -> int:
        """
        Get the number of bytes downloaded.
        This method Only counts full, verified, pieces, not single blocks.
        """
        # Return the total number of bytes downloaded
        return len(self.have_pieces) * self.torrent.piece_length

    @property
    def bytes_uploaded(self) -> int:
        # TODO Add support for sending data
        return 0

    def get_bitfield(self):

        bitfield = '0'*self.total_pieces
        bitfield += '0' * (self.total_pieces % 8) # padding at end
        bitfield = list(bitfield)
        for pcs in self.have_pieces:
            # print('current pcs idx is ' + str(pcs.index))
            bitfield[pcs.index] = '1'
        # print(len(bitfield))
        # print(bitfield)
        return ''.join(bitfield)

    def has_piece(self, index):
        for pcs in self.have_pieces:
            if pcs.index == index:
                return True
        return False


    def add_peer(self, peer_id, bitfield):
        """
        Adds a peer and the bitfield representing the pieces the peer has.
        """
        #print(bitfield)
        for idx in range(self.total_pieces):
            self.rarest_pieces[idx] += bitfield[idx]
        #print(self.rarest_pieces)
        self.peers[peer_id] = bitfield

    def update_peer(self, peer_id, index: int):
        """
        Updates the information about which pieces a peer has (reflects a Have
        message).
        """
        if peer_id in self.peers:
            self.peers[peer_id][index] = 1

    def remove_peer(self, peer_id):
        """
        Tries to remove a previously added peer (e.g. used if a peer connection
        is dropped)
        """
        if peer_id in self.peers:
            del self.peers[peer_id]

    def next_request(self, peer_id) -> Block:
        """
        Get the next Block that should be requested from the given peer.
        If there are no more blocks left to retrieve or if this peer does not
        have any of the missing pieces None is returned
        """
        # print(self.peers)
        # print(peer_id)
        if peer_id not in self.peers:
            print('peer id not in peer')
            return None

        block = self._expired_requests(peer_id)
        if not block:
            block = self._next_ongoing(peer_id)
            if not block:
                block = self._next_missing(peer_id)
        # print('the returning blcok is')
        # print(block)
        return block

    def block_received(self, peer_id, piece_index, block_offset, data):
        """
        This method must be called when a block has successfully been retrieved
        by a peer.
        Once a full piece have been retrieved, a SHA1 hash control is made. If
        the check fails all the pieces blocks are put back in missing state to
        be fetched again. If the hash succeeds the partial piece is written to
        disk and the piece is indicated as Have.
        """
        logging.debug('Received block {block_offset} for piece {piece_index} '
                      'from peer {peer_id}: '.format(block_offset=block_offset,
                                                     piece_index=piece_index,
                                                     peer_id=peer_id))

        # Remove from pending requests
        for index, request in enumerate(self.pending_blocks):
            if request.block.piece == piece_index \
               and request.block.offset == block_offset:
                del self.pending_blocks[index]
                break

        pieces = []
        for p in self.ongoing_pieces:
             if p.index == piece_index:
                 pieces.append(p)
        if len(pieces) > 0:
            piece = pieces[0]
        else:
            pieces = None

        if piece:
            piece.block_received(block_offset, data)
            if piece.is_complete():
                piece_hash = sha1(piece.data).digest()
                if piece.hash == piece_hash:
                    self._write(piece)
                    self.have_pieces.append(piece)
                    self.ongoing_pieces.remove(piece)
                    complete = (self.total_pieces -
                                len(self.missing_pieces) -
                                len(self.ongoing_pieces))

                    print ('{complete} / {total} pieces downloaded {per:.3f} %'
                        .format(complete=complete,
                                total=self.total_pieces,
                                per=(complete/self.total_pieces)*100))
                else:
                    print ('Discarding corrupt piece {index}'
                                 .format(index=piece.index))

                    #Reset all blocks to Missing
                    for block in piece.blocks:
                        block.status = Block.Missing
        else:
            print ('Trying to update piece that is not ongoing!')

    def _expired_requests(self, peer_id) -> Block:
        """
        Go through previously requested blocks, if any one have been in the
        requested state for longer than `MAX_PENDING_TIME` return the block to
        be re-requested.
        If no pending blocks exist, None is returned
        """
        #Check whether blocks in pending list is expiredd using 'max_pending_time'
        current = int(round(time.time() * 1000))
        for req_bloc in self.pending_blocks:
            if self.peers[peer_id][req_bloc.block.piece]:
                if self.max_pending_time + req_bloc.added  < current:
                    b_offset =req_bloc.block.offset
                    req_piece=req_bloc.block.piece
                    print ('Re-requesting block '+ b_offset + ' for piece ' + req_piece)
                    # Reset expiration timer
                    req_bloc.added = current
                    return req_bloc.block
        return None

    def _next_ongoing(self, peer_id) -> Block:
        """
        Go through the ongoing pieces and return the next block to be
        requested or None if no block is left to be requested.
        """
        for piece in self.ongoing_pieces:
            if self.peers[peer_id][piece.index]:
                # Is there any blocks left to request in this piece
                block = piece.get_next_request()
                if block:
                    self.pending_blocks.append(
                        PendingRequest(block, int(round(time.time() * 1000))))
                    return block
        return None

    def _next_missing(self, peer_id) -> Block:
        """
        Go through the missing pieces and return the next block to request
        or None if no block is left to be requested.
        This will change the state of the piece from missing to ongoing - thus
        the next call to this function will not continue with the blocks for
        that piece, rather get the next missing piece.
        """
        # print('looking at self.missing pieces')
        # print(self.missing_pieces)
        random.shuffle(self.missing_pieces)
        for index, piece in enumerate(self.missing_pieces):
            if self.peers[peer_id][piece.index]:
                # Move this piece from missing to ongoing
                piece = self.missing_pieces.pop(index)
                self.ongoing_pieces.append(piece)
                # The missing pieces does not have any previously requested
                # blocks (then it is ongoing).
                return piece.get_next_request()
        return None

    def get_block(self, piece_index, block_index):
        pos = piece_index * self.torrent.piece_length + block_index * REQ_SIZE
        os.lseek(self.fd, pos, os.SEEK_SET)
        data = os.read(self.fd, REQ_SIZE)
        return data

    def _write(self, piece):
        """
        Write the given piece to disk
        """
        pos = piece.index * self.torrent.piece_length
        os.lseek(self.fd, pos, os.SEEK_SET)
        os.write(self.fd, piece.data)
