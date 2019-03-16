import unittest

from torrent import Torrent


class UbuntuTorrentTests(unittest.TestCase):
    def setUp(self):
        self.t = Torrent('debian-8.3.0-i386-netinst.iso.torrent')

    def test_instantiate(self):
        self.assertIsNotNone(self.t)

    def test_is_single_file(self):
        self.assertFalse(self.t.multi_file)

    def test_announce(self):
        self.assertEqual(
            'http://bttracker.debian.org:6969/announce', self.t.announce)

    def test_piece_length(self):
        self.assertEqual(
            262144, self.t.piece_length)

    def test_file(self):
        self.assertEqual(1, len(self.t.file))
        self.assertEqual(
            'debian-8.3.0-i386-netinst.iso', self.t.file[0].name)
        self.assertEqual(330301440, self.t.file[0].length)

    def test_hash_value(self):
        self.assertEqual(
            b'~\xf0\xc0\xbc\xab\xae\x9f!\xe86L\xf3\xbb\x9d0\x11\xa6\x9e\xe0j',
            self.t.info_hash)

    def test_total_size(self):
        self.assertEqual(330301440, self.t.total_length)

    def test_pieces(self):
        self.assertEqual(1260, len(self.t.pieces))


class SXSWTorrentTests(unittest.TestCase):
    """
    Represents a multi-file torrent which is not supported
    """
    def test_instantiate(self):
        with self.assertRaises(RuntimeError):
            Torrent('multifile.torrent')

if __name__ == '__main__':
    unittest.main()
