import numpy as np
from collections import namedtuple
from dataclasses import dataclass
from typing import Any
import time
import random
from threeviz.api import plot_3d, plot_pose, plot_line_seg
import cv2
from random import seed
from maze_nn import create_maze_solving_network, predict_on_model, preprocess_image
from collections import deque

"""
- States
  - 0 means free
  - -1 mean not traversable
  - 1 means goal?
"""

def anneal_probability(itr, maxitr, start_itr, start_prob):
    m = (1-start_prob)/(maxitr-start_itr)
    b = start_prob
    return m*(itr - start_itr) + b

@dataclass
class SingleStep:
    st: Any
    stn: Any
    at: int
    rt: float
    done: bool


class Agent:
    def __init__(self, i=0, j=0):
        self.i = i
        self.j = j

    @property
    def loc(self):
        return (self.i, self.j)

    def vmove(self, direction):
        direction = 1 if direction > 0 else -1
        return Agent(self.i + direction, self.j)

    def hmove(self, direction):
        direction = 1 if direction > 0 else -1
        return Agent(self.i, self.j + direction)

    def __repr__(self):
        return str(self.loc)

class QLearning:
    def __init__(self, num_states, num_actions, lr=0.1, discount_factor=0.99):
        self.q = np.zeros((num_states, num_actions))
        self.a = lr
        self.g = discount_factor

    def update(self, st, at, rt, st1):
        q = self.q
        a = self.a
        g = self.g
        q[st, at] = (1 - a)*q[st, at] + a * (rt + g * np.max(q[st1]))


class Maze:
    def __init__(self, rows=4, columns=4):
        self.env = np.zeros((rows, columns))
        self.mousy = Agent(0, 0)

    def reset(self):
        self.mousy.i = 0
        self.mousy.j = 0

    def in_bounds(self, i, j):
        nr, nc = self.env.shape
        return i >= 0 and i < nr and j >= 0 and j < nc

    def agent_in_bounds(self, a):
        return self.in_bounds(a.i, a.j)

    def is_valid_new_agent(self, a):
        return self.agent_in_bounds(a)

    @property
    def all_actions(self):
        a = self.mousy
        return [
            a.vmove(1),
            a.vmove(-1),
            a.hmove(1),
            a.hmove(-1),
        ]

    def apply_action(self, idx):
        moves = self.all_actions
        assert idx >= 0 and idx < len(moves), f"Index {idx} is not valid for picking a move"
        move = moves[idx]
        score = -0.1
        win_score = 100
        death_score = -10
        wall_score = -0.5
        if not self.is_valid_new_agent(move):
            return -0.5, False
        self.do_a_move(move)
        if self.has_won():
            return win_score, True
        if self.has_died():
            return death_score, True

        return score, False

    def do_a_move(self, a):
        assert self.is_valid_new_agent(a), "Mousy can't go there"
        self.mousy = a
        return 10 if self.has_won() else -0.1

    def has_won(self):
        a = self.mousy
        return self.env[a.i, a.j] == 1

    def has_died(self):
        a = self.mousy
        return self.env[a.i, a.j] == -1

    def has_ended(self):
        return self.has_won() or self.has_died()

    def visualize(self):
        nr, nc = self.env.shape
        z = -0.1
        a = self.mousy
        plot_line_seg(0, 0, z, nr, 0, z, 'e1', size=0.2, color='red')
        plot_line_seg(0, 0, z, 0, nc, z, 'e2', size=0.2, color='red')
        plot_line_seg(0, nc, z, nr, nc, z, 'e3', size=0.2, color='red')
        plot_line_seg(nr, 0, z, nr, nc, z, 'e4', size=0.2, color='red')
        plot_3d(*get_midpoint_for_loc(a.i, a.j), z, 'mousy', color='blue', size=1)
        plot_3d(*get_midpoint_for_loc(nr-1,nc-1), z, 'goal', color='green', size=1)

        xarr, yarr = np.where(self.env == -1)
        plot_3d(xarr + 0.5, yarr + 0.5, [z]*len(xarr), 'obstacles', size=1.0)

    def to_image(self, image_shape=64):
        a = self.mousy
        e = self.env
        imout = np.expand_dims(np.ones_like(e)*255, -1).astype('uint8')
        imout = np.dstack((imout, imout, imout))
        imout[e==-1, :] = 0
        imout[a.i, a.j, :-1] = 0
        imout[-1, -1, ::2] = 0
        return cv2.resize(imout, (image_shape, image_shape), interpolation=cv2.INTER_NEAREST)

def get_midpoint_for_loc(i, j):
    return i + 0.5, j + 0.5

def make_test_maze(s=4):
    seed(9001)
    m = Maze(s,s)
    e = m.env
    h, w = e.shape
    e[-1, -1] = 1
    for i in range(len(e)):
        for j in range(len(e[i])):
            if i in [0, h-1] and j in [0, w-1]:
                continue
            if random.random() < 0.3:
                e[i, j] = -1
    seed(time.time())
    return m

def run_episode(m, model, eps, memory, verbose=False):
    # if not memory:
    #     memory = []
    m.reset()
    final_score = 0

    itr = 0
    agents = []

    while not m.has_ended(): # and not m.has_died():
        itr += 1
        # if random.random() > anneal_probability(i, max_episodes, switch_episodes, 0.5) or i < switch_episodes:
        if random.random() < eps:
            idx = random.randint(0, 3)
        else:
            idx = predict_on_model(m.to_image(), model, False)

        at = idx
        state = m.to_image(64)
        rt, _ = m.apply_action(at)
        next_state = m.to_image(64)
        final_score += rt

        if verbose:
            m.visualize()
            time.sleep(0.05)

        done = m.has_ended()
        memory.append(SingleStep(st=state, stn=next_state, rt=rt, at=at, done=done))

    print(f"finished episode with final score of {final_score} and in {itr} iterations")
    return memory

def main():
    g = 0.95
    memory = deque(maxlen=10000)

    model = create_maze_solving_network()

    s = 6

    m = make_test_maze(s)

    eps = 0.5
    decay_factor = 0.999

    for i in range(1000000):

        for i in range(10):
            run_episode(m, model, eps, memory, False)
        if len(memory) < 500:
            continue

        steps = random.sample(memory, min(256, len(memory)))

        inputs = []
        outputs = []

        for s in steps:
            x = s.st
            r = s.rt
            target_vector = predict_on_model(s.stn, model, True)
            if not s.done:
                target = r + g * np.max(target_vector)
            else:
                target = r
            target_vector[s.at] = target

            inputs.append(preprocess_image(x, expand=False))
            outputs.append(target_vector)

        model.fit(np.stack(inputs, 0), np.stack(outputs, 0), epochs=1)

        # eps *= decay_factor

        m.reset()
        m.visualize()
        idx = 0
        while not m.has_ended():
            time.sleep(0.1)
            m.apply_action(predict_on_model(m.to_image(64), model, False))
            m.visualize()
            idx += 1
            if idx > 20:
                break

def vis_tests():
    m = make_test_maze(8)
    im = m.to_image(256)
    cv2.imwrite('/home/jack/test.jpg', im)
    m.visualize()

    while True:
        idx = predict_on_model(im, model)
        print(m.apply_action(idx))
        im = m.to_image(256)
        cv2.imwrite('/home/jack/test.jpg', im)
        m.visualize()
        time.sleep(0.1)

if __name__ == '__main__':
    main()
    # vis_tests()
