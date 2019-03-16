from collections import namedtuple
from hashlib import sha1

from bencoding import Decoder
from bencoding import Encoder

TorrentFile = namedtuple('TorrentFile', ['name', 'length'])

class Torrent:
    def __init__(self, filename):
        self.filename = filename
        self.file = []

        with open(self.filename,'rb') as f:
            meta_info = f.read()
            self.meta_info = Decoder(meta_info).decode()
            info = Encoder(self.meta_info[b'info']).encode()
            self.info_hash = sha1(info).digest()
            self._check_files()

    def _check_files(self):
        #no muti file
        if self.multi_file:
            raise RuntimeError('Multi-file torrents is not supported!')

        self.file.append(TorrentFile(self.meta_info[b'info'][b'name'].decode('utf-8'),
                                     self.meta_info[b'info'][b'length']))

    @property
    def pieces(self):
        """
            ecah piece has 20 bytes sha1
        """
        offset = 0
        tmp_info = self.meta_info[b'info'][b'pieces']
        piece = []
        length = len(tmp_info)

        while offset < length:
            tmp_offset = offset+20
            piece.append(tmp_info[offset:tmp_offset])
            offset += 20
        return piece

    @property
    def announce(self)->str:
        """
            URL to tracker
        """
        return self.meta_info[b'announce'].decode('utf-8')

    @property
    def multi_file(self) -> bool:
        return b'files' in self.meta_info[b'info']

    @property
    def piece_length(self)->int:
        """
            each piece's length
        """
        return self.meta_info[b'info'][b'piece length']

    @property
    def total_length(self)->int:
        return self.file[0].length

    @property
    def output_file(self):
        return self.meta_info[b'info'][b'name'].decode('utf-8')

    def __str__(self):
        return 'Filename: {0}\n'  \
               'File length: {1}\n' \
               'Announce URL: {2}\n' \
               'Hash: {3}'.format(self.meta_info[b'info'][b'name'],
                                  self.meta_info[b'info'][b'length'],
                                  self.meta_info[b'announce'],
                                  self.info_hash)
