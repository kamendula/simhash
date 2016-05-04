# Created by 1e0n in 2013
#encoding:utf-8
from __future__ import division, unicode_literals

import sys
import re
import hashlib
import logging
import collections
from itertools import groupby

if sys.version_info[0] >= 3:
    basestring = str
    unicode = str
    long = int
else:
    range = xrange


class Simhash(object):

    def __init__(self, value, f=64, reg=r'[\w\u4e00-\u9fcc]+', hashfunc=None):
        """
        `f` is the dimensions of fingerprints

        `reg` is meaningful only when `value` is basestring and describes
        what is considered to be a letter inside parsed string. Regexp
        object can also be specified (some attempt to handle any letters
        is to specify reg=re.compile(r'\w', re.UNICODE))
        reg:默认单词和中文，但是只在value是basestring的时候有用。

        `hashfunc` accepts a utf-8 encoded string and returns a unsigned
        integer in at least `f` bits.
        """

        self.f = f
        self.reg = reg
        self.value = None

        if hashfunc is None:
            def _hashfunc(x):
                return int(hashlib.md5(x).hexdigest(), 16)  #hashlib的md5算法，返回十六进制的值。

            self.hashfunc = _hashfunc
        else:
            self.hashfunc = hashfunc

        #根据不同类型的value，获取不同的value值。

        #value是simhash,那么就直接取其值。
        if isinstance(value, Simhash):
            self.value = value.value

        #如果输入的是字符串，先对字符串进行处理再计算
        elif isinstance(value, basestring):
            self.build_by_text(unicode(value))

        #如果是iterable:集合或者迭代器， 就直接计算
        elif isinstance(value, collections.Iterable):
            self.build_by_features(value)

        #如果是long值，直接赋值
        elif isinstance(value, long):
            self.value = value
        else:
            raise Exception('Bad parameter with type {}'.format(type(value)))

    #对一个字符串，默认四个为一组，组成列表。例如：abcdefg会划分为 abcd bcde cdef defg
    def _slide(self, content, width=4):
        return [content[i:i + width] for i in range(max(len(content) - width + 1, 1))]

    #取出其中的reg部分，并划分
    def _tokenize(self, content):
        content = content.lower()
        content = ''.join(re.findall(self.reg, content))
        ans = self._slide(content)
        return ans

    def build_by_text(self, content):
        features = self._tokenize(content)
        #groupby会把相邻的同样的合并到一起，形成一个grouper
        #k是uniq之后的值，g里面包含同样的str集合形成的grouper
        #在这里，就是每个k值以及他出现的次数作为权重。
        features = {k:sum(1 for _ in g) for k, g in groupby(sorted(features))}
        return self.build_by_features(features)

    def build_by_features(self, features):
        """
        `features` might be a list of unweighted tokens (a weight of 1
                   will be assumed), a list of (token, weight) tuples or
                   a token -> weight dict.
        """
        v = [0] * self.f
        #构造list，每个值在f位的每个位上都有1一个1，其它都是0
        masks = [1 << i for i in range(self.f)]
        if isinstance(features, dict):
            features = features.items()
        for f in features:
            #feature里面的都是str,那么权重默认为1
            if isinstance(f, basestring):
                h = self.hashfunc(f.encode('utf-8'))
                w = 1
            else:
                #如果传进来的是iterable,即自身带了权重，那么就采用其权重。
                assert isinstance(f, collections.Iterable)
                h = self.hashfunc(f[0].encode('utf-8'))
                w = f[1]
            #对于所形成的hash值h，看h的每一位，如果该位是1则+w否则-w
            #多个feature叠加
            for i in range(self.f):
                v[i] += w if h & masks[i] else -w
        ans = 0
        #遍历所有的位，如果feature叠加的v[i]>=0，就该位置1，否则置默认的0
        for i in range(self.f):
            if v[i] >= 0:
                ans |= masks[i]
        self.value = ans


    def distance(self, another):
        assert self.f == another.f
        #异或之后，利用mask来只取f长度,mask = (1 << self.f) - 1
        x = (self.value ^ another.value) & ((1 << self.f) - 1)
        ans = 0

        #求其中所有1的个数
        while x:
            ans += 1
            x &= fx - 1
        return ans


class SimhashIndex(object):

    def __init__(self, objs, f=64, k=2):
        """
        `objs` is a list of (obj_id, simhash)
        obj_id is a string, simhash is an instance of Simhash
        `f` is the same with the one for Simhash
        `k` is the tolerance
        """
        self.k = k
        self.f = f
        count = len(objs)
        logging.info('Initializing %s data.', count)

        self.bucket = collections.defaultdict(set)
        #添加所有的simhash到bucket中。
        for i, q in enumerate(objs):
            if i % 10000 == 0 or i == count - 1:
                logging.info('%s/%s', i + 1, count)

            self.add(*q)

    def get_near_dups(self, simhash):
        """
        `simhash` is an instance of Simhash
        return a list of obj_id, which is in type of str
        """
        assert simhash.f == self.f

        ans = set()

        for key in self.get_keys(simhash):
            #key在simhash中存在，也在本身存在，那么就有可能是相似的。
            #接下来进行完整的判断就行了，d = simhash.distance(sim2)
            dups = self.bucket[key]
            logging.debug('key:%s', key)
            if len(dups) > 200:
                logging.warning('Big bucket found. key:%s, len:%s', key, len(dups))

            for dup in dups:
                sim2, obj_id = dup.split(',', 1)
                sim2 = Simhash(long(sim2, 16), self.f)

                d = simhash.distance(sim2)
                if d <= self.k:
                    ans.add(obj_id)
        return list(ans)

    #将simhash添加到bucket中。
    #将f划分为k+1份后，每份->(simhash value值，obj_id)
    #也就是说，会有多个hash值对应到(simhash value值，obj_id)
    def add(self, obj_id, simhash):
        """
        `obj_id` is a string
        `simhash` is an instance of Simhash
        """
        assert simhash.f == self.f

        for key in self.get_keys(simhash):
            v = '%x,%s' % (simhash.value, obj_id)
            self.bucket[key].add(v)

    def delete(self, obj_id, simhash):
        """
        `obj_id` is a string
        `simhash` is an instance of Simhash
        """
        assert simhash.f == self.f

        for key in self.get_keys(simhash):
            v = '%x,%s' % (simhash.value, obj_id)
            if v in self.bucket[key]:
                self.bucket[key].remove(v)

    @property

    #利用抽屉原理，例如如果两个simhash值距离差异设定k=3，即有3位是不同的，
    # 那么就把总位数长度f划分为四份，根据抽屉原理，这两个simhash值总有一份是完全相同的。
    def offsets(self):
        """
        You may optimize this method according to <http://www.wwwconference.org/www2007/papers/paper215.pdf>
        """
        return [self.f // (self.k + 1) * i for i in range(self.k + 1)]

    def get_keys(self, simhash):
        for i, offset in enumerate(self.offsets):
            #划分为多份之后，每份的位都置1
            if i == (len(self.offsets) - 1):
                m = 2 ** (self.f - offset) - 1
            else:
                m = 2 ** (self.offsets[i + 1] - offset) - 1
            #只取每份中的值，返回划分的每份的值和offsets的第几个
            c = simhash.value >> offset & m
            yield '%x:%x' % (c, i)

    def bucket_size(self):
        return len(self.bucket)
