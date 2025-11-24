import time
from collections import deque
from loguru import logger
import copy
import re


NON_WORD_PATTERN = re.compile(r'[^\u4e00-\u9fffA-Za-z0-9_\s]')
def words_only(text):
    """
    Keep only:
        - Chinese characters (U+4E00–U+9FFF)
        - Latin letters, digits, underscore
        - Whitespace (as separators)
    Strip punctuation, emojis, etc.
    Return a list of tokens (Chinese blocks or Latin word blocks).
    """
    # 1. Replace all non-allowed characters with a space
    cleaned = NON_WORD_PATTERN.sub(' ', text)

    # 2. Normalize multiple spaces and split into tokens
    tokens = cleaned.split()

    return "".join(tokens)


class StreamTextReleaser:
    def __init__(self):
        self.st_time = None   # estimate starting time when text starts happening
        self.prev_sentence_len = None # length of previous sentence
        self.text_queue = deque()

        self.ST_DELTA = 0.   # estimated time that xiaozhi starts speaking
        self.AVG_WORD_PER_SEC = 0.19 # sec/word  ; avg is 0.224; choose something slightly faster to feel smoother

    
    def start(self):
        if self.has_started():
            return None
        
        self.reset()
        logger.info("STARTING text releaser")
        self.st_time = time.time() + self.ST_DELTA

    def reset(self):
        self.st_time = None
        self.prev_sentence_len = None
        self.text_queue = deque()
    
    def get_sentence(self):
        if len(self.text_queue) == 0:
            return None

        if self.prev_sentence_len is None:
            sent = self.text_queue.popleft()
            self.prev_sentence_len = len(words_only(copy.deepcopy(sent)))
            return sent
        
        if not ((time.time() - self.st_time) >= (self.prev_sentence_len*self.AVG_WORD_PER_SEC)):
            return

        sent = self.text_queue.popleft()
        self.prev_sentence_len = len(words_only(copy.deepcopy(sent)))
        self.st_time = time.time()

        return sent

    def add_sentence(self, sentence):
        if sentence is None:
            return
        
        self.text_queue.append(sentence)
    
    def has_started(self):
        return not (self.st_time is None)
    
    def is_done(self):
        return not (len(self.text_queue) > 0)
