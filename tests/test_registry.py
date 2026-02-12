"""A3: Document Registry tests - No API key required."""
from app.db.models import UserModel


class TestRegistryAdd:
    """A3.1 - A3.2: Adding documents."""

    async def test_add_with_collections(self, registry):
        """A3.1: Document stored with collections list."""
        await registry.add("doc1", "contract.pdf", ".pdf", 10, collections=["legal-compliance", "contracts-agreements"])
        doc = await registry.get("doc1")
        assert doc is not None
        assert sorted(doc["collections"]) == ["contracts-agreements", "legal-compliance"]
        assert doc["filename"] == "contract.pdf"
        assert doc["chunk_count"] == 10
        assert doc["user_id"] == "admin"

    async def test_add_without_collections(self, registry):
        """A3.2: Document stored with default collections=["other"]."""
        await registry.add("doc2", "readme.txt", ".txt", 3)
        doc = await registry.get("doc2")
        assert doc is not None
        assert doc["collections"] == ["other"]

    async def test_add_with_user_id(self, registry, db_session):
        """Document stored with custom user_id."""
        db_session.add(UserModel(user_id="jason", display_name="Jason"))
        await db_session.flush()

        await registry.add("doc3", "note.md", ".md", 2, user_id="jason")
        doc = await registry.get("doc3")
        assert doc is not None
        assert doc["user_id"] == "jason"


class TestRegistryList:
    """A3.3 - A3.5: Listing and filtering."""

    async def test_list_all(self, registry):
        """A3.3: list_all returns all documents."""
        await registry.add("d1", "a.pdf", ".pdf", 5, collections=["legal-compliance"])
        await registry.add("d2", "b.pdf", ".pdf", 8, collections=["medical-healthcare"])
        await registry.add("d3", "c.txt", ".txt", 2)

        all_docs = await registry.list_all()
        assert len(all_docs) == 3

    async def test_list_all_with_user_filter(self, registry, db_session):
        """list_all with user_id filter."""
        db_session.add(UserModel(user_id="jason", display_name="Jason"))
        await db_session.flush()

        await registry.add("d1", "a.pdf", ".pdf", 5, user_id="admin")
        await registry.add("d2", "b.pdf", ".pdf", 8, user_id="jason")

        admin_docs = await registry.list_all(user_id="admin")
        assert len(admin_docs) == 1
        assert admin_docs[0]["doc_id"] == "d1"

        jason_docs = await registry.list_all(user_id="jason")
        assert len(jason_docs) == 1
        assert jason_docs[0]["doc_id"] == "d2"

    async def test_list_by_collection(self, registry):
        """A3.4: Filter by collection name (multi-collection membership)."""
        await registry.add("d1", "a.pdf", ".pdf", 5, collections=["legal-compliance", "contracts-agreements"])
        await registry.add("d2", "b.pdf", ".pdf", 8, collections=["legal-compliance", "litigation-disputes"])
        await registry.add("d3", "c.pdf", ".pdf", 3, collections=["medical-healthcare"])

        legal_docs = await registry.list_by_collection("legal-compliance")
        assert len(legal_docs) == 2

        contracts_docs = await registry.list_by_collection("contracts-agreements")
        assert len(contracts_docs) == 1

    async def test_list_by_collection_with_user_filter(self, registry, db_session):
        """Filter by collection + user_id."""
        db_session.add(UserModel(user_id="jason", display_name="Jason"))
        await db_session.flush()

        await registry.add("d1", "a.pdf", ".pdf", 5, collections=["legal-compliance"], user_id="admin")
        await registry.add("d2", "b.pdf", ".pdf", 8, collections=["legal-compliance"], user_id="jason")

        admin_legal = await registry.list_by_collection("legal-compliance", user_id="admin")
        assert len(admin_legal) == 1
        assert admin_legal[0]["doc_id"] == "d1"

    async def test_list_by_collection_nonexistent(self, registry):
        """A3.5: Empty list for nonexistent collection."""
        await registry.add("d1", "a.pdf", ".pdf", 5, collections=["legal-compliance"])
        result = await registry.list_by_collection("nonexistent")
        assert result == []


class TestRegistryGet:
    """A3.6 - A3.7: Getting individual documents."""

    async def test_get_existing(self, registry):
        """A3.6: Returns document metadata."""
        await registry.add("doc1", "test.pdf", ".pdf", 5, collections=["legal-compliance"])
        doc = await registry.get("doc1")
        assert doc is not None
        assert doc["doc_id"] == "doc1"
        assert doc["filename"] == "test.pdf"
        assert doc["file_type"] == ".pdf"
        assert "uploaded_at" in doc
        assert "collections" in doc
        assert "user_id" in doc

    async def test_get_nonexistent(self, registry):
        """A3.7: Returns None for missing doc."""
        doc = await registry.get("does_not_exist")
        assert doc is None


class TestRegistryUpdateCollections:
    """Update collections on existing documents."""

    async def test_update_collections(self, registry):
        await registry.add("doc1", "test.pdf", ".pdf", 5, collections=["other"])
        result = await registry.update_collections("doc1", ["legal-compliance", "contracts-agreements"])
        assert result is True

        doc = await registry.get("doc1")
        assert sorted(doc["collections"]) == ["contracts-agreements", "legal-compliance"]

    async def test_update_nonexistent(self, registry):
        result = await registry.update_collections("nonexistent", ["legal-compliance"])
        assert result is False


class TestRegistryGetAllCollections:
    """Get all unique collections."""

    async def test_get_all_collections(self, registry):
        await registry.add("d1", "a.pdf", ".pdf", 5, collections=["legal-compliance", "contracts-agreements"])
        await registry.add("d2", "b.pdf", ".pdf", 8, collections=["legal-compliance", "medical-healthcare"])

        all_cols = await registry.get_all_collections()
        assert "legal-compliance" in all_cols
        assert "contracts-agreements" in all_cols
        assert "medical-healthcare" in all_cols
        assert len(all_cols) == 3

    async def test_get_all_collections_with_user_filter(self, registry, db_session):
        db_session.add(UserModel(user_id="jason", display_name="Jason"))
        await db_session.flush()

        await registry.add("d1", "a.pdf", ".pdf", 5, collections=["legal-compliance"], user_id="admin")
        await registry.add("d2", "b.pdf", ".pdf", 8, collections=["medical-healthcare"], user_id="jason")

        admin_cols = await registry.get_all_collections(user_id="admin")
        assert admin_cols == ["legal-compliance"]

        jason_cols = await registry.get_all_collections(user_id="jason")
        assert jason_cols == ["medical-healthcare"]


class TestRegistryRemove:
    """A3.8 - A3.9: Removing documents and count."""

    async def test_remove_existing(self, registry):
        """A3.8: Document removed, count decremented."""
        await registry.add("d1", "a.pdf", ".pdf", 5)
        await registry.add("d2", "b.pdf", ".pdf", 3)
        assert await registry.count() == 2

        result = await registry.remove("d1")
        assert result is True
        assert await registry.get("d1") is None
        assert await registry.count() == 1

    async def test_remove_nonexistent(self, registry):
        """A3.8: Removing nonexistent doc returns False."""
        result = await registry.remove("does_not_exist")
        assert result is False

    async def test_count_accuracy(self, registry):
        """A3.9: Count correct after add/remove operations."""
        assert await registry.count() == 0
        await registry.add("d1", "a.pdf", ".pdf", 5)
        assert await registry.count() == 1
        await registry.add("d2", "b.pdf", ".pdf", 3)
        assert await registry.count() == 2
        await registry.remove("d1")
        assert await registry.count() == 1
        await registry.remove("d2")
        assert await registry.count() == 0


class TestUserRegistry:
    """User registry tests."""

    async def test_default_user_exists(self, user_registry):
        """Default admin user auto-created in fixture."""
        assert await user_registry.exists("admin")
        user = await user_registry.get("admin")
        assert user["display_name"] == "Admin"

    async def test_add_user(self, user_registry):
        user = await user_registry.add("jason", "Jason")
        assert user["user_id"] == "jason"
        assert user["display_name"] == "Jason"
        assert await user_registry.exists("jason")

    async def test_list_users(self, user_registry):
        await user_registry.add("jason", "Jason")
        await user_registry.add("guest", "Guest")

        users = await user_registry.list_all()
        assert len(users) == 3  # admin + jason + guest

    async def test_get_nonexistent_user(self, user_registry):
        assert await user_registry.get("nonexistent") is None
