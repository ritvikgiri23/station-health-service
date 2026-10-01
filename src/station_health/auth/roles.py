from enum import StrEnum


class Role(StrEnum):
    INGEST = "ingest"
    READ = "read"
    ADMIN = "admin"
