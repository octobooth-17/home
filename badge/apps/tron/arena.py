"""Grid-based light-cycle rules, independent of badge graphics and input."""

import random


RIGHT, DOWN, LEFT, UP = range(4)
DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))
COUNTDOWN_MS = 2400


class Arena:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.reset()

    def reset(self):
        self.cells = bytearray(self.width * self.height)
        self.heads = [
            (self.width // 4, self.height // 2),
            (self.width - 1 - self.width // 4, self.height // 2),
        ]
        self.directions = [RIGHT, LEFT]
        self.paths = [[self.heads[0]], [self.heads[1]]]
        for rider, (x, y) in enumerate(self.heads):
            self.cells[y * self.width + x] = rider + 1
        self.pending = None
        self.countdown = COUNTDOWN_MS
        self.accumulator = 0
        self.elapsed = 0
        self.steps = 0
        self.result = None
        self.crashes = []

    @property
    def interval(self):
        return max(80, 125 - self.steps // 12)

    def free(self, x, y):
        return (0 <= x < self.width and 0 <= y < self.height
                and self.cells[y * self.width + x] == 0)

    def target(self, position, direction):
        dx, dy = DIRECTIONS[direction]
        return position[0] + dx, position[1] + dy

    def turn(self, direction):
        if self.result is not None or self.pending is not None:
            return
        current = self.directions[0]
        if direction != current and direction != (current + 2) % 4:
            self.pending = direction

    def room(self, x, y):
        # A bounded flood fill avoids choosing a long corridor into a tiny pocket.
        seen = {(x, y)}
        queue = [(x, y)]
        cursor = 0
        while cursor < len(queue) and len(seen) < 96:
            px, py = queue[cursor]
            cursor += 1
            for dx, dy in DIRECTIONS:
                nx, ny = px + dx, py + dy
                if (nx, ny) not in seen and self.free(nx, ny):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
                    if len(seen) >= 96:
                        break
        return len(seen)

    def choose_cpu(self):
        current = self.directions[1]
        best, best_score = current, -1
        for direction in (current, (current + 1) % 4, (current - 1) % 4):
            x, y = self.target(self.heads[1], direction)
            if not self.free(x, y):
                continue
            dx, dy = DIRECTIONS[direction]
            distance = 0
            while distance < 12 and self.free(x + dx * distance, y + dy * distance):
                distance += 1
            score = self.room(x, y) * 4 + distance * 2 + random.randrange(4)
            if direction == current:
                score += 4
            if score > best_score:
                best, best_score = direction, score
        return best

    def step(self):
        if self.result is not None:
            return
        old_directions = self.directions[:]
        if self.pending is not None:
            self.directions[0] = self.pending
            self.pending = None
        self.directions[1] = self.choose_cpu()
        targets = [self.target(self.heads[i], self.directions[i]) for i in range(2)]
        dead = [not self.free(*target) for target in targets]
        if targets[0] == targets[1]:
            dead = [True, True]
        self.steps += 1
        if any(dead):
            self.result = "draw" if all(dead) else ("cpu" if dead[0] else "player")
            self.crashes = [targets[i] for i in range(2) if dead[i]]
            return
        for rider, (x, y) in enumerate(targets):
            self.cells[y * self.width + x] = rider + 1
            path = self.paths[rider]
            if len(path) == 1 or old_directions[rider] != self.directions[rider]:
                path.append((x, y))
            else:
                path[-1] = (x, y)
        self.heads = targets

    def advance(self, milliseconds):
        if self.result is not None:
            return
        if self.countdown:
            consumed = min(self.countdown, milliseconds)
            self.countdown -= consumed
            milliseconds -= consumed
        self.accumulator += milliseconds
        while self.result is None and self.accumulator >= self.interval:
            interval = self.interval
            self.accumulator -= interval
            self.elapsed += interval
            self.step()
