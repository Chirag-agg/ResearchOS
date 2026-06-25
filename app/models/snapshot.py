from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field
from datetime import datetime
import os
import hashlib
import msgpack
import zstandard as zstd
from typing import Dict, Any

class KnowledgeSnapshot(SQLModel, table=True):
    """
    Immutable representation of the pipeline state at a specific point in time.
    Stores metadata in SQL and payloads compressed on disk.
    """
    __tablename__ = "knowledge_snapshots"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="research_sessions.id", ondelete="CASCADE", index=True)
    stage: str = Field(index=True, description="e.g. POST_OBSERVATION, POST_CLAIM")
    manifest_hash: str = Field(index=True, description="SHA256 of the payload for deduplication")
    parent_snapshot_id: Optional[UUID] = Field(default=None, foreign_key="knowledge_snapshots.id", description="For Git-style delta references")
    storage_uri: str = Field(description="Path to the msgpack.zstd file containing deltas or full payload")
    compression: str = Field(default="zstd")
    pipeline_fingerprint: str = Field(default="unknown", description="Hash of the stage versions, prompts, configs, models")
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SnapshotManager:
    def __init__(self, storage_dir: str = "snapshots"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.cctx = zstd.ZstdCompressor(level=3)
        self.dctx = zstd.ZstdDecompressor()
        
    def save_snapshot(
        self, 
        session_id: UUID, 
        stage: str, 
        payload: Dict[str, Any], 
        pipeline_fingerprint: str,
        parent_snapshot_id: Optional[UUID] = None,
        db_session=None
    ) -> KnowledgeSnapshot:
        # If parent exists, payload should ideally be a delta. For now we assume payload is the delta format.
        # Serialize to msgpack
        packed = msgpack.packb(payload, use_bin_type=True)
        # Compress
        compressed = self.cctx.compress(packed)
        
        # Calculate deduplication hash
        manifest_hash = hashlib.sha256(compressed).hexdigest()
        
        file_path = os.path.join(self.storage_dir, f"{manifest_hash}.msgpack.zstd")
        
        # Only write if it doesn't exist
        if not os.path.exists(file_path):
            with open(file_path, "wb") as f:
                f.write(compressed)
                
        snapshot = KnowledgeSnapshot(
            session_id=session_id,
            stage=stage,
            manifest_hash=manifest_hash,
            parent_snapshot_id=parent_snapshot_id,
            storage_uri=file_path,
            compression="zstd",
            pipeline_fingerprint=pipeline_fingerprint
        )
        
        if db_session:
            db_session.add(snapshot)
            db_session.commit()
            
        return snapshot
        
    def load_snapshot(self, snapshot: KnowledgeSnapshot) -> Dict[str, Any]:
        with open(snapshot.storage_uri, "rb") as f:
            compressed = f.read()
            
        decompressed = self.dctx.decompress(compressed)
        payload = msgpack.unpackb(decompressed, raw=False)
        return payload
