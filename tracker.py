import aiohttp
import random
import logging
import socket


from struct import unpack
from urllib.parse import urlencode

import bencoding


class TrackerResponse:

    def __init__(self, response):
        self.response = response


    @property
    def failure(self):
        if b'failure reason' in self.response:
            return self.response[b'failure reason'].decode('utf-8')
        return None




    def __str__(self):
        return "incomplete: {incomplete}\n" \
               "complete: {complete}\n" \
               "interval: {interval}\n" \
               "peers: {peers}\n".format(incomplete=self.incomplete, complete=self.complete, interval=self.interval, peers=", ".join([x for (x, _) in self.peers]))


    @property
    def interval(self):
        return self.response.get(b'interval', 0)

    @property
    def complete(self):
        return self.response.get(b'complete', 0)

    @property
    def incomplete(self):
        return self.response.get(b'incomplete', 0)



    @property
    def peers(self):
        try:
            peers = self.response[b'peers']
            if type(peers) == list:
                logging.debug('Dictionary model peers are returned by tracker')
                raise NotImplementedError()
            else:
                logging.debug('Binary model peers are returned by tracker')
                peers = [peers[i:i+6] for i in range(0, len(peers), 6)]
                return [(socket.inet_ntoa(p[:4]), _dePort(p[4:]))
                        for p in peers]
        except KeyError as e:
            logging.warning('No peers returned from tracker')



class Tracker:

    def __init__(self, torrent):
        self.torrent = torrent
        self.peer_id = _get_peerId()
        self.http_client = aiohttp.ClientSession()

    async def connect(self,
                      first: bool=None,
                      uploaded: int=0,
                      downloaded: int=0):

        params = {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'port': 6889,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': self.torrent.total_length - downloaded,
            'compact': 1}

        if first:
            params['event'] = 'started'

        url = self.torrent.announce + '?' + urlencode(params)

        logging.info('Connecting to tracker at: ' + url)

        async with self.http_client.get(url) as response:
            if not response.status == 200:
                raise ConnectionError('Unable to connect to tracker')
            data = await response.read()
            return TrackerResponse(bencoding.Decoder(data).decode())

    async def close(self):
        await self.http_client.close()


    def _tracker_constructor(self):
        return {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'port': 6889,
            # TODO Update stats when communicating with tracker
            'uploaded': 0,
            'downloaded': 0,
            'left': 0,
            'compact': 1}


def _dePort(port):

    return unpack(">H", port)[0]


def _get_peerId():

    return '-PC0001-' + ''.join(
        [str(random.randint(0, 9)) for _ in range(12)])
