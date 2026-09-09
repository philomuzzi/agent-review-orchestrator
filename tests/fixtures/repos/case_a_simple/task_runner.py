# sync task runner (Case A: simple change)

import time


class SyncTask:
    """Runs a list of steps to completion."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.current = 0

    def run(self):
        while self.current < len(self.steps):
            step = self.steps[self.current]
            step()
            self.current += 1


if __name__ == "__main__":
    SyncTask([lambda: print("step"), lambda: time.sleep(0)]).run()
