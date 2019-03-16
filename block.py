class Block:
    """
    The block is a partial piece, this is what is requested and transferred
    between peers.
    A block is most often of the same size as the REQUEST_SIZE, except for the
    final block which might (most likely) is smaller than REQUEST_SIZE.
    """
    Missing = 0
    Pending = 1
    Retrieved = 2

    def __init__(self, piece, offset, length):
        self.status = Block.Missing
        self.data = None
        self.piece = piece
        self.offset = offset
        self.length = length




class Piece:
    """
    The piece is a part of of the torrents content. Each piece except the final
    piece for a torrent has the same length (the final piece might be shorter).
    A piece is what is defined in the torrent meta-data. However, when sharing
    data between peers a smaller unit is used - this smaller piece is refereed
    to as `Block` by the unofficial specification (the official specification
    uses piece for this one as well, which is slightly confusing).
    """
    def __init__(self, index, blocks, hash_value):
        self.index = index
        self.blocks = blocks
        self.hash = hash_value

    def reset(self):
        """
        Reset all blocks to Missing regardless of current state.
        """
        for block in self.blocks:
            block.status = Block.Missing

    def get_next_request(self):
        # Get the next Block to be requested
        need = []
        for bloc in self.blocks:
            if bloc.status is Block.Missing:
                need.append(bloc)

        if len(need) > 0:
            need[0].status = Block.Pending
            return need[0]
        return None

    def block_received(self, offset, data):
        #Update block information that the given block is now received
        matches = []
        for bloc in self.blocks:
             if bloc.offset == offset:
                 matches.append(bloc)

        if len(matches)>0:
             block = matches[0]
        else:
            block = None

        if block:
            block.status = Block.Retrieved
            block.data = data
        else:
            print ('This block does not exist')

    def is_complete(self):
        #Checks if all blocks for this piece is retrieved (regardless of SHA1)
        not_retrieved = []
        for bloc in self.blocks:
             if bloc.status is not Block.Retrieved:
                 not_retrieved.append(bloc)

        if len(not_retrieved) == 0:
            return True

        return False


    @property
    def data(self):
        #Combine all data according to their offset in ascending order
        retrieved = sorted(self.blocks, key=lambda b: b.offset)
        blocks_data = [b.data for b in retrieved]
        return b''.join(blocks_data)

# The type used for keeping track of pending request that can be re-issued
# PendingRequest = namedtuple('PendingRequest', ['block', 'added'])
