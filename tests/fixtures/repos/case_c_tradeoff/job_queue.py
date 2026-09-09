# job queue with two backends (Case C: human trade-off)

class MemoryQueue:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)

    def pop(self):
        return self.items.pop(0) if self.items else None


class SqliteQueue:
    """Persistent queue; requires the sqlite3 job table to exist."""

    def __init__(self, connection):
        self.connection = connection

    def push(self, item):
        self.connection.execute("INSERT INTO jobs (payload) VALUES (?)", (item,))

    def pop(self):
        row = self.connection.execute("SELECT id, payload FROM jobs ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        self.connection.execute("DELETE FROM jobs WHERE id = ?", (row[0],))
        return row[1]
