from collections import OrderedDict


TOKEN_DICT = b'd'
TOKEN_END = b'e'
TOKEN_STRING_SEPARATOR = b':'
TOKEN_INTEGER = b'i'
TOKEN_LIST = b'l'


class Decoder:

    def __init__(self, data: bytes):
        if not isinstance(data, bytes):
            raise TypeError('Argument "data" must be of type bytes')
        self._data = data
        self._index = 0

    def decode(self):

        c = self._pop()
        if c is None:
            raise EOFError('Unexpected end-of-file')
        elif c == TOKEN_INTEGER:
            self._consume()
            return self._decode_int()
        elif c == TOKEN_DICT:
            self._consume()
            return self._decode_dict()
        elif c == TOKEN_LIST:
            self._consume()
            return self._decode_list()
        elif c == TOKEN_END:
            return None
        elif c in b'01234567899':
            return self._decode_string()
        else:
            raise RuntimeError('Invalid token read at {0}'.format(
                str(self._index)))

    def _pop(self):

        if self._index + 1 >= len(self._data):
            return None
        return self._data[self._index:self._index + 1]

    def _consume(self) -> bytes:

        self._index += 1

    def _decode_int(self):
        return int(self._read_until(TOKEN_END))

    def _decode_list(self):
        res = []
        while self._data[self._index: self._index + 1] != TOKEN_END:
            res.append(self.decode())
        self._consume()
        return res

    def _decode_dict(self):
        res = OrderedDict()
        while self._data[self._index: self._index + 1] != TOKEN_END:
            key = self.decode()
            obj = self.decode()
            res[key] = obj
        self._consume()
        return res

    def _decode_string(self):
        bytes_to_read = int(self._read_until(TOKEN_STRING_SEPARATOR))
        data = self._read(bytes_to_read)
        return data

    def _read(self, length: int) -> bytes:

        if self._index + length > len(self._data):
            raise IndexError('Cannot read {0} bytes from current position {1}'
                             .format(str(length), str(self._index)))
        res = self._data[self._index:self._index+length]
        self._index += length
        return res

    def _read_until(self, token: bytes) -> bytes:

        try:
            occ = self._data.index(token, self._index)
            result = self._data[self._index:occ]
            self._index = occ + 1
            return result
        except ValueError:
            raise RuntimeError('Unable to find token {0}'.format(
                str(token)))
class Encoder:
    def __init__(self,data):
        self._data = data

    def encode(self)->bytes:
        return self._encode_next_byte(self._data)

    def _encode_next_byte(self,data):
        if type(data) == int:
            return self._encode_int(data)
        elif type(data) == str:
            return self._encode_string(data)
        elif type(data) == list:
            return self._encode_list(data)
        elif type(data) == dict or type(data) == OrderedDict:
            return self._encode_dict(data)
        elif type(data) == bytes:
            return self._encode_byte(data)
        else:
            return None

    def _encode_int(self,data):
        return str.encode('i'+str(data)+'e')

    def _encode_string(self,data):
        return str.encode(str(len(data))+":"+str(data))

    def _encode_list(self,data):
        list = bytearray('l','utf-8')
        list += b''.join([self._encode_next_byte(element)
                         for element in data])
        list += b'e'
        return list

    def _encode_dict(self,data:dict)->bytes:
        dict = bytearray("d","utf-8")
        for k,v in data.items():
            key = self._encode_next_byte(k)
            val = self._encode_next_byte(v)
            if key and val:
                dict += key
                dict += val
            else:
                raise RuntimeError("dict error")
        dict +=b'e'
        return dict

    def _encode_byte(self,data:str):
        array = bytearray()
        array += str.encode(str(len(data)))
        array += b':'
        array += data
        return array
