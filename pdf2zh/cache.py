import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from peewee import SQL, AutoField, CharField, DateTimeField, Model, SqliteDatabase, TextField

# we don't init the database here
db = SqliteDatabase(None)
logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Collapse whitespace and normalize Unicode form for cache matching.

    Two extractions of the same sentence can differ in line-wrap whitespace or
    NFC/NFD form without differing in meaning; normalizing lets both hit the
    same cache entry. Case and punctuation are left alone - folding those risks
    treating two different source strings as the same one.
    """
    collapsed = re.sub(r"\s+", " ", text).strip()
    return unicodedata.normalize("NFC", collapsed)


class _TranslationCache(Model):
    id = AutoField()
    translate_engine = CharField(max_length=20)
    translate_engine_params = TextField()
    original_text = TextField()
    # Populated for every row so lookups can fall back to it; not unique on its
    # own, since two different source strings can normalize to the same text.
    normalized_text = TextField()
    translation = TextField()
    # Provenance: which book/run produced this entry and under what subject
    # area, so a future QA or terminology-review pass can tell where a
    # translation came from. Neither is used to filter lookups yet - a v1
    # translation memory intentionally reuses any matching entry regardless of
    # domain or source document.
    domain = CharField(max_length=64, null=True)
    source_document = TextField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    class Meta:
        database = db
        indexes = (
            (("translate_engine", "translate_engine_params", "normalized_text"), False),
        )
        constraints = [SQL("""
            UNIQUE (
                translate_engine,
                translate_engine_params,
                original_text
                )
            ON CONFLICT REPLACE
            """)]


class TranslationCache:
    @staticmethod
    def _sort_dict_recursively(obj):
        if isinstance(obj, dict):
            return {
                k: TranslationCache._sort_dict_recursively(v)
                for k in sorted(obj.keys())
                for v in [obj[k]]
            }
        elif isinstance(obj, list):
            return [TranslationCache._sort_dict_recursively(item) for item in obj]
        return obj

    def __init__(
        self,
        translate_engine: str,
        translate_engine_params: dict = None,
        *,
        domain: str = None,
        source_document: str = None,
    ):
        assert (
            len(translate_engine) < 20
        ), "current cache require translate engine name less than 20 characters"
        self.translate_engine = translate_engine
        self.replace_params(translate_engine_params)
        # Constant for the lifetime of one translator instance - one run
        # translates one document under (at most) one domain - so these ride
        # along on every row this instance writes rather than being passed
        # into each set() call.
        self.domain = domain
        self.source_document = source_document

    # The program typically starts multi-threaded translation
    # only after cache parameters are fully configured,
    # so thread safety doesn't need to be considered here.
    def replace_params(self, params: dict = None):
        if params is None:
            params = {}
        self.params = params
        params = self._sort_dict_recursively(params)
        self.translate_engine_params = json.dumps(params)

    def update_params(self, params: dict = None):
        if params is None:
            params = {}
        self.params.update(params)
        self.replace_params(self.params)

    def add_params(self, k: str, v):
        self.params[k] = v
        self.replace_params(self.params)

    # Since peewee and the underlying sqlite are thread-safe,
    # get and set operations don't need locks.
    def get(self, original_text: str) -> Optional[str]:
        result = _TranslationCache.get_or_none(
            translate_engine=self.translate_engine,
            translate_engine_params=self.translate_engine_params,
            original_text=original_text,
        )
        if result is not None:
            return result.translation

        # Exact miss: fall back to a normalized match - e.g. the same sentence
        # re-extracted with different line-wrap whitespace, or a different
        # Unicode form of the same characters. Skipped when normalizing does
        # nothing, since that is exactly the exact-match query just run.
        normalized = normalize_text(original_text)
        if normalized == original_text:
            return None
        result = (
            _TranslationCache.select()
            .where(
                (_TranslationCache.translate_engine == self.translate_engine)
                & (_TranslationCache.translate_engine_params == self.translate_engine_params)
                & (_TranslationCache.normalized_text == normalized)
            )
            .first()
        )
        return result.translation if result else None

    def set(self, original_text: str, translation: str):
        try:
            _TranslationCache.create(
                translate_engine=self.translate_engine,
                translate_engine_params=self.translate_engine_params,
                original_text=original_text,
                normalized_text=normalize_text(original_text),
                translation=translation,
                domain=self.domain,
                source_document=self.source_document,
            )
        except Exception as e:
            logger.debug(f"Error setting cache: {e}")


def init_db(remove_exists=False):
    cache_folder = os.path.join(os.path.expanduser("~"), ".cache", "pdf2zh")
    os.makedirs(cache_folder, exist_ok=True)
    # The current version does not support database migration, so add the
    # version number to the file name. v2 adds normalized_text/domain/
    # source_document/created_at; a v1 cache is simply left behind rather than
    # migrated - it is a disposable performance cache, not a record of truth.
    cache_db_path = os.path.join(cache_folder, "cache.v2.db")
    if remove_exists and os.path.exists(cache_db_path):
        os.remove(cache_db_path)
    db.init(
        cache_db_path,
        pragmas={
            "journal_mode": "wal",
            "busy_timeout": 1000,
        },
    )
    db.create_tables([_TranslationCache], safe=True)


def init_test_db():
    import tempfile

    cache_db_path = tempfile.mktemp(suffix=".db")
    test_db = SqliteDatabase(
        cache_db_path,
        pragmas={
            "journal_mode": "wal",
            "busy_timeout": 1000,
        },
    )
    test_db.bind([_TranslationCache], bind_refs=False, bind_backrefs=False)
    test_db.connect()
    test_db.create_tables([_TranslationCache], safe=True)
    return test_db


def clean_test_db(test_db):
    test_db.drop_tables([_TranslationCache])
    test_db.close()
    db_path = test_db.database
    if os.path.exists(db_path):
        os.remove(test_db.database)
    wal_path = db_path + "-wal"
    if os.path.exists(wal_path):
        os.remove(wal_path)
    shm_path = db_path + "-shm"
    if os.path.exists(shm_path):
        os.remove(shm_path)


init_db()
