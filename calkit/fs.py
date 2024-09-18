"""A filesystem-like object that follows ``fsspec`` and interacts with Calkit
cloud storage to unify operations between private and public storage.

The basic operation is as follows:
1. Make a request to the Calkit API over HTTP.
2. Use the URL in the response to get or put the file where it should go.
"""

from fsspec import AbstractFileSystem
from fsspec.spec import AbstractBufferedFile


class CalkitFileSystem(AbstractFileSystem):
    protocol = "ck"

    def _open(
        self,
        path,
        mode="rb",
        block_size=None,
        autocommit=True,
        cache_options=None,
        **kwargs,
    ):
        return CalkitFile(
            self,
            path,
            mode,
            block_size,
            autocommit,
            cache_options=cache_options,
            **kwargs,
        )


class CalkitFile(AbstractBufferedFile):
    def _upload_chunk(self, final=False):
        return super()._upload_chunk(final)

    def _initiate_upload(self):
        return super()._initiate_upload()

    def _fetch_range(self, start, end):
        return super()._fetch_range(start, end)
