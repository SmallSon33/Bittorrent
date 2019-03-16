import bitstring
import logging
import struct
import asyncio

from concurrent.futures import CancelledError
from asyncio import Queue


REQ_SIZE = 2**14

INTERESTED = 'interested'
CHOKED = 'choked'
PENDING_REQ = 'pending_request'
STOPPED = 'stopped'

class ProtocolError(BaseException):
    pass

class PeerConnection:


    """
    use one available peer in queue and try to peform bittorrent handshake based on
    peer detail.

    the initial state after succesful handshake is CHOKED. Will wait to be unchoked
    after sending intered message

    """
    def __init__(self, queue: Queue, info_hash, peer_id, piece_manager, on_block_cb=None, server_mode=False):

        """
        Create a PeerConnection and add it to asyncio event loop

        piece_manager: the object responsible to determine which piece to request
        on_block_cb: call back function to call when a block is received from remote peer
        """

        self.my_state = []  # tracks current state
        self.peer_state = []
        self.queue = queue
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.remote_id = None
        self.writer = None
        self.reader = None
        self.piece_manager = piece_manager
        self.on_block_cb = on_block_cb
        if not server_mode:
            self.future = asyncio.ensure_future(self._start())  # Start this worker
        self.server_mode = server_mode

    async def _start(self, reader=None, writer=None):
        while STOPPED not in self.my_state:
            try:
                if self.server_mode:
                    self.reader = reader
                    self.writer = writer
                else:
                    ip, port = await self.queue.get()
                    # if ip == 0 and port == 0:
                    logging.info('Assigned with peer ip = {ip}'.format(ip=ip))
                    self.reader, self.writer = await asyncio.open_connection(ip, port)
                    logging.info('Connection open to peer: {ip}'.format(ip=ip))
                #init handshake
                await self._init_proto()

            except ProtocolError as e:
                logging.exception('Protocol error')
            except (ConnectionRefusedError, TimeoutError):
                logging.warning('Unable to connect to peer')
            except (ConnectionResetError, CancelledError):
                logging.warning('Connection closed')
            except Exception as e:
                logging.exception('An error occurred')
                self.cancel()
                raise e
            self.cancel()

    # send cancel message to peer to close connection
    def cancel(self):
        logging.info('Closing peer {id} connection'.format(id=self.remote_id))
        if not self.future.done():
            self.future.cancel()
        if self.writer:
            self.writer.close()
        #if not self.server_mode:
        self.queue.task_done()

    def stop(self):
        self.my_state.append(STOPPED)
        if not self.server_mode and not self.future.done():
            self.future.cancel()

    async def init_server(reader, writer):
        print('recieved connection to server')
        await self.start(reader, writer)

    async def _init_proto(self):
        try:
            buffer = await self._handshake()

            # init state
            self.my_state.append(CHOKED)
            await self._send_bitfield()
            await self._notify_interested()
            await self._start_proto(buffer)

        except ProtocolError as e:
            logging.exception('Protocol error')
        except (ConnectionRefusedError, TimeoutError):
            logging.warning('Unable to connect to peer')
        except (ConnectionResetError, CancelledError):
            logging.warning('Connection closed')
        except Exception as e:
            logging.exception('An error occurred')
            self.cancel()
            raise e
        self.cancel()

    async def _start_proto(self, buffer):
        #start to read stream frm Connection
        async for message in PeerStreamIterator(self.reader, buffer):
            if STOPPED in self.my_state:
                break
            if type(message) is BitField:
                self.piece_manager.add_peer(self.remote_id, message.bitfield)
            elif type(message) is Handshake:
                await self._send_bitfield()
            elif type(message) is Interested:
                if INTERESTED not in self.peer_state:
                    self.peer_state.append(INTERESTED)
                    await self._notify_unchoke()
            elif type(message) is NotInterested:
                if INTERESTED in self.peer_state:
                    self.peer_instate.remove(INTERESTED)
            elif type(message) is Choke:
                if CHOKED not in self.my_state:
                    self.my_state.append(CHOKED)
            elif type(message) is Unchoke:
                if CHOKED in self.my_state:
                    self.my_state.remove(CHOKED)
            elif type(message) is Have:
                self.piece_manager.update_peer(self.remote_id, message.index)
            elif type(message) is KeepAlive:
                pass
            elif type(message) is Request:
                if self.piece_manager.has_piece(message.index):
                    await self._send_block(message.index, message.begin)
                else:
                    await self._notify_choke()
            elif type(message) is Piece:
                self.my_state.remove(PENDING_REQ)
                self.on_block_cb(peer_id=self.remote_id, piece_index=message.index, block_offset = message.begin, data = message.block )
            else:
                # Have not considered cancel
                pass
            if CHOKED not in self.my_state:
                if PENDING_REQ not in self.my_state:
                    self.my_state.append(PENDING_REQ)
                    await self._request_piece()
        self.cancel()

    async def _request_piece(self):
        # print('requesting piece')
        block = self.piece_manager.next_request(self.remote_id)
        # print(block)
        if block:
            # print('in side if block')
            message = Request(block.piece, block.offset, block.length).encode()

            logging.debug('Requesting block {block} for piece {piece} '
                          'of {length} bytes from peer {peer}'.format(
                            piece=block.piece,
                            block=block.offset,
                            length=block.length,
                            peer=self.remote_id))
            # print(message)
            self.writer.write(message)
            await self.writer.drain()

    async def _send_block(self, piece_index, block_offset):
        data = self.piece_manager.get_block(piece_index, block_offset)
        message = Piece(piece_index, block_offset, data)
        self.writer.write(message.encode())
        await self.writer.drain()

    async def _notify_interested(self):
        message = Interested()
        self.writer.write(message.encode())
        await self.writer.drain()
    # establish handshake with remote peer

    async def _notify_choke(self):
        message = Choke()
        self.writer.write(message.encode())
        await self.writer.drain()

    async def _notify_unchoke(self):
        message = Unchoke()
        self.writer.write(message.encode())
        await self.writer.drain()

    async def _send_bitfield(self):
        data = self.piece_manager.get_bitfield()
        # print(len(data))
        data = int(data,2).to_bytes(int(len(data)/8), byteorder='big')
        # print('inside send bitfield')
        # print(data)
        bits_length = len(data)
        # print(bits_length)
        message = struct.pack('>Ib' + str(bits_length) + 's',
                           1 + bits_length,
                           PeerMessage.BitField,
                           data)
        # print(message)
        self.writer.write(message)
        await self.writer.drain()

    async def _handshake(self):
        self.writer.write(Handshake(self.info_hash, self.peer_id).encode())
        await self.writer.drain()

        buf = b''
        while len(buf) < Handshake.length:
            buf = await self.reader.read(PeerStreamIterator.SIZE)
        response = Handshake.decode(buf[:Handshake.length])
        if not response:
            raise ProtocolError('Unable receive and parse a handshake')
        if not response.info_hash == self.info_hash:
            raise ProtocolError('Handshake has invalid info_hash')

        self.remote_id = response.peer_id
        logging.info('Handshake was succesfull')
        return buf[Handshake.length:]




class PeerStreamIterator:
    """
    continously read from given stream and parse valid bittorrent message.
    """

    SIZE = 10*1024

    def __init__(self, reader,initial:bytes=None):
        self.reader = reader
        self.buffer = initial if initial else b''

    async def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            try:
                # print('waiting for data')
                if len(self.buffer) > 4:
                    message = self.parse()
                    # print(message)
                    if message:
                        return message
                data = await self.reader.read(PeerStreamIterator.SIZE)
                # print(data)
                # print('data received')
                if data:
                    self.buffer += data
                    message = self.parse()
                    # print(message)
                    if message:
                        return message
                else:
                    logging.debug('No data from peer socket stream')
                    if self.buffer:
                        message = self.parse()
                        if message:
                            return message
                    raise StopAsyncIteration()
            except ConnectionResetError:
                logging.debug('Connection closed by peer')
                raise StopAsyncIteration()
            except CancelledError:
                raise StopAsyncIteration()
            except StopAsyncIteration as e:
                # Catch to stop logging
                raise e
            except Exception:
                logging.exception('Error when iterating over stream!')
                raise StopAsyncIteration()
        raise StopAsyncIteration()

    def parse(self):

        #return None if no message could be parse
        """
        message has the structure <length prefix><message ID><payload>
        """

        hdrLen = 4
        # print(self.buffer)
        if len(self.buffer) > 4: #4 bytes is the least requirement to identify message
            # print(self.buffer[0:4])
            # print(struct.unpack('>I', self.buffer[0:4]))
            message_length = struct.unpack('>I', self.buffer[0:4])[0]
            # print(message_length)
            # print(self.buffer)
        if message_length == 0:
            return KeepAlive()
        if len(self.buffer) >= message_length:
            message_id = struct.unpack('>b', self.buffer[4:5])[0]
            def eatUp():
                # print('consuming buffer')
                # print(self.buffer)
                self.buffer = self.buffer[hdrLen + message_length:]
                # print(self.buffer)
            def _data():
                return self.buffer[:hdrLen + message_length]

            if message_id is PeerMessage.BitField:
                data = _data()
                # print(data)
                eatUp()
                return BitField.decode(data)
            elif message_id is PeerMessage.Interested:
                eatUp()
                return Interested()
            elif message_id is PeerMessage.NotInterested:
                eatUp()
                return NotInterested()
            elif message_id is PeerMessage.Choke:
                eatUp()
                return Choke()
            elif message_id is PeerMessage.Unchoke:
                eatUp()
                return Unchoke()
            elif message_id is PeerMessage.Have:
                data = _data()
                eatUp()
                return Have.decode(data)
            elif message_id is PeerMessage.Piece:
                data = _data()
                eatUp()
                return Piece.decode(data)
            elif message_id is PeerMessage.Request:
                data = _data()
                eatUp()
                return Request.decode(data)
            elif message_id is PeerMessage.Cancel:
                data = _data()
                eatUp()
                return Cancel.decode(data)
            else:
                logging.info('Unsupported message id received!')

        else:
            logging.debug('Not enough bytes in buffer to parse')

        return None

class PeerMessage:
    Choke = 0
    Unchoke = 1
    Interested = 2
    NotInterested = 3
    Have = 4
    BitField = 5
    Request = 6
    Piece = 7
    Cancel = 8
    Port = 9
    Handshake = None  # Handshake is not really part of the messages
    KeepAlive = None  # Keep-alive has no ID according to spec

    def encode(self) -> bytes:
        # encode interface
        pass

    @classmethod
    def decode(cls, data: bytes):
        # decode interface
        pass

class Handshake(PeerMessage):
    length = 1 + 19 + 8 +20 +20 # 68

    def __init__(self, info_hash: bytes, peer_id: bytes):
        if isinstance(info_hash, str):
            info_hash = info_hash.encode('utf-8')
        if isinstance(peer_id, str):
            peer_id  = peer_id.encode('utf-8')
        self.info_hash = info_hash
        self.peer_id = peer_id

    def encode(self)-> bytes:
        return struct.pack(
            '>B19s8x20s20s',
            19,                         # Single byte (B)
            b'BitTorrent protocol',     # String 19s
                                        # Reserved 8x (pad byte, no value)
            self.info_hash,             # String 20s
            self.peer_id)

    @classmethod
    def decode(cls, data: bytes):
        if len(data) < Handshake.length:
            return None
        info = struct.unpack('>B19s8x20s20s', data)
        return cls(info_hash=info[2],peer_id=info[3])

    def __str__(self):
        return 'Handshake'

class KeepAlive(PeerMessage):

    def __str__(self):
        return 'KeepAlive'

class BitField(PeerMessage):
    """
    The BitField is a message with variable length where the payload is a
    bit array representing all the bits a peer have (1) or does not have (0).

    Message format:
        <len=0001+X><id=5><bitfield>
    """
    def __init__(self, data):
        self.bitfield = bitstring.BitArray(bytes=data)

    def encode(self) -> bytes:
        """
        Encodes this object instance to the raw bytes representing the entire
        message (ready to be transmitted).
        """
        bits_length = len(self.bitfield)
        return struct.pack('>Ib' + str(bits_length) + 's',
                           1 + bits_length,
                           PeerMessage.BitField,
                           self.bitfield)

    @classmethod
    def decode(cls, data: bytes):
        # print('bitfield from peer')
        # print(data)
        message_length = struct.unpack('>I', data[:4])[0]
        logging.debug('Decoding BitField of length: {length}'.format(
            length=message_length))

        parts = struct.unpack('>Ib' + str(message_length - 1) + 's', data)
        print(len(parts[2]))
        return cls(parts[2])

    def __str__(self):
        return 'BitField'

class Interested(PeerMessage):
    # does not have data to decode
    def encode(self) -> bytes:
        return struct.pack('>Ib',
                           1,  # Message length
                           PeerMessage.Interested)

    def __str__(self):
        return 'Interested'


class NotInterested(PeerMessage):
    # does not have data to decode
    def encode(self) -> bytes:
        return struct.pack('>Ib',
                           1,  # Message length
                           PeerMessage.NotInterested)

    def __str__(self):
        return 'NotInterested'

class Choke(PeerMessage):
    # does not have data to decode
    def encode(self) -> bytes:
        return struct.pack('>Ib',
                           1,  # Message length
                           PeerMessage.Choke)

    def __str__(self):
        return 'Choke'

class Unchoke(PeerMessage):
    # does not have data to decode
    def encode(self) -> bytes:
        return struct.pack('>Ib',
                           1,  # Message length
                           PeerMessage.Unchoke)

    def __str__(self):
        return 'Unchoke'

class Have(PeerMessage):
    """
    The 'have' message's payload is a single number, the index which that downloader just completed and checked the hash of.
    """

    def __init__(self, index: int):
        self.index = index

    def encode(self):
        return struct.pack('>IbI',
                           5,  # Message length
                           PeerMessage.Have,
                           self.index)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug('Decoding Have of length: {length}'.format(
            length=len(data)))
        index = struct.unpack('>IbI', data)[2]
        return cls(index)

    def __str__(self):
        return 'Have'

class Request(PeerMessage):
    """
    'request' messages contain an index, begin, and length. The last two are byte offsets.
    Length is generally a power of two unless it gets truncated by the end of the file.
    All current implementations use 2^14 (16 kiB), and close connections which request an
     amount greater than that.
    """

    def __init__(self, index: int, begin: int, length: int = REQ_SIZE):
        """
        Constructs the Request message.

        :param index: The zero based piece index
        :param begin: The zero based offset within a piece
        :param length: The requested length of data (default 2^14)
        """
        self.index = index
        self.begin = begin
        self.length = length

    def encode(self):
        return struct.pack('>IbIII',
                           13,
                           PeerMessage.Request,
                           self.index,
                           self.begin,
                           self.length)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug('Decoding Request of length: {length}'.format(
            length=len(data)))
        # Tuple with (message length, id, index, begin, length)
        parts = struct.unpack('>IbIII', data)
        return cls(parts[2], parts[3], parts[4])

    def __str__(self):
        return 'Request'

class Piece(PeerMessage):
    """
    messages contain an index, begin, and piece. Note that they are correlated
    with request messages implicitly. It's possible for an unexpected piece to
    arrive if choke and unchoke messages are sent in quick succession and/or transfer
    is going very slowly.

    Message format:
        <length prefix><message ID><index><begin><block>
    """
    # The Piece message length without the block data
    length = 9

    def __init__(self, index: int, begin: int, block: bytes):
        """
        Constructs the Piece message.

        :param index: The zero based piece index
        :param begin: The zero based offset within a piece
        :param block: The block data
        """
        self.index = index
        self.begin = begin
        self.block = block

    def encode(self):
        message_length = Piece.length + len(self.block)
        return struct.pack('>IbII' + str(len(self.block)) + 's',
                           message_length,
                           PeerMessage.Piece,
                           self.index,
                           self.begin,
                           self.block)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug('Decoding Piece of length: {length}'.format(
            length=len(data)))
        length = struct.unpack('>I', data[:4])[0]
        parts = struct.unpack('>IbII' + str(length - Piece.length) + 's',
                              data[:length+4])
        return cls(parts[2], parts[3], parts[4])

    def __str__(self):
        return 'Piece'


class Cancel(PeerMessage):
    """
    They have the same payload as request messages.
    The cancel message is used to cancel a previously requested block.

    Message format:
         <len=0013><id=8><index><begin><length>
    """
    def __init__(self, index, begin, length: int = REQ_SIZE):
        self.index = index
        self.begin = begin
        self.length = length

    def encode(self):
        return struct.pack('>IbIII',
                           13,
                           PeerMessage.Cancel,
                           self.index,
                           self.begin,
                           self.length)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug('Decoding Cancel of length: {length}'.format(
            length=len(data)))
        # Tuple with (message length, id, index, begin, length)
        parts = struct.unpack('>IbIII', data)
        return cls(parts[2], parts[3], parts[4])

    def __str__(self):
        return 'Cancel'
