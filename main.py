import argparse
import random
import torch
from torch.autograd import Variable

from agent import Agent
from env import Env
from memory import ReplayMemory
from test import test


parser = argparse.ArgumentParser(description='Rainbow')
parser.add_argument('--seed', type=int, default=123, help='Random seed')
parser.add_argument('--game', type=str, default='Pong', help='ATARI game')
parser.add_argument('--T-max', type=int, default=int(5e7), metavar='STEPS', help='Number of training steps')
parser.add_argument('--max-episode-length', type=int, default=int(1e6), metavar='LENGTH', help='Max episode length')
parser.add_argument('--history-length', type=int, default=4, metavar='T', help='Number of consecutive states processed')  # TODO: Cyclic buffer
parser.add_argument('--hidden-size', type=int, default=512, metavar='SIZE', help='Network hidden size')
parser.add_argument('--noisy-std', type=float, default=0.5, metavar='σ', help='Initial standard deviation of noisy linear layers')
parser.add_argument('--atoms', type=int, default=51, metavar='C', help='Discretised size of value distribution')
parser.add_argument('--V-min', type=float, default=-10, metavar='V', help='Minimum of value distribution support')
parser.add_argument('--V-max', type=float, default=10, metavar='V', help='Maximum of value distribution support')
parser.add_argument('--model', type=str, metavar='PARAMS', help='Pretrained model (state dict)')
parser.add_argument('--memory-capacity', type=int, default=10000, metavar='CAPACITY', help='Experience replay memory capacity')  # TODO: 1e6
parser.add_argument('--replay-frequency', type=int, default=4, metavar='k', help='Frequency of sampling from memory')
# TODO: Memory prioritisation (w/ alpha and beta hyperparams)?
parser.add_argument('--discount', type=float, default=0.99, metavar='γ', help='Discount factor')
parser.add_argument('--target-update', type=int, default=1000, metavar='τ', help='Number of steps after which to update target network')  # TODO: 32000
parser.add_argument('--reward-clip', type=int, default=1, metavar='VALUE', help='Reward clipping (0 to disable)')
parser.add_argument('--lr', type=float, default=0.0000625, metavar='η', help='Learning rate')
parser.add_argument('--adam-eps', type=float, default=1.5e-4, metavar='ε', help='Adam epsilon')
parser.add_argument('--batch-size', type=int, default=32, metavar='SIZE', help='Batch size')  # Assumed to be < learn_start
parser.add_argument('--learn-start', type=int, default=1000, metavar='STEPS', help='Number of steps before starting training')  # TODO: 8e4
parser.add_argument('--max-gradient-norm', type=float, default=10, metavar='VALUE', help='Max value of gradient L2 norm for gradient clipping')
parser.add_argument('--evaluate', action='store_true', help='Evaluate only')
parser.add_argument('--evaluation-interval', type=int, default=1000, metavar='STEPS', help='Number of training steps between evaluations')  # TODO: 25000
parser.add_argument('--evaluation-episodes', type=int, default=10, metavar='N', help='Number of evaluation episodes to average over')
parser.add_argument('--evaluation-size', type=int, default=500, metavar='N', help='Number of transitions to use for validating Q')  # TODO: Val replay mem
parser.add_argument('--render', action='store_true', help='Render evaluation agent')


# Setup
args = parser.parse_args()
print(' ' * 26 + 'Options')
for k, v in vars(args).items():
  print(' ' * 26 + k + ': ' + str(v))
torch.manual_seed(args.seed)
env = Env(args)
env.seed(args.seed)
env.train()
action_space = env.action_space()


# Agent
dqn = Agent(args, env)
mem = ReplayMemory(args.memory_capacity)
# Training setup
T, done = 0, True

# Construct validation memory
val_mem = ReplayMemory(args.evaluation_size)
while T < args.evaluation_size:
  if done:
    state, done = env.reset(), False

  val_mem.append(state, None, None, None)
  state, _, done = env.step(random.randint(0, action_space - 1))
  T += 1

if args.evaluate:
  dqn.eval()  # Set DQN (policy network) to evaluation mode
  avg_reward, avg_Q = test(args, 0, dqn, val_mem, evaluate=True)  # Test
  print('Avg. reward: ' + str(avg_reward) + ' | Avg. Q: ' + str(avg_Q))
else:
  # Training loop
  dqn.train()
  T, done = 0, True
  while T < args.T_max:
    if done:
      state, done = Variable(env.reset()), False
      dqn.reset_noise()  # Draw a new set of noisy weights per episode

    action = dqn.act(state)  # Choose an action greedily (with noisy weights)

    next_state, reward, done = env.step(action)  # Step
    if args.reward_clip > 0:
      reward = max(min(reward, args.reward_clip), -args.reward_clip)  # Clip rewards
    T += 1

    mem.append(state.data, action, reward, done)  # Append transition to memory
    if done:
      mem.append(next_state, None, None, None)  # TODO: Work out if this is correct

    # Train and test
    if T >= args.learn_start:
      if T % args.replay_frequency == 0:
        dqn.learn(mem)  # Train with n-step distributional double-Q learning

      if T % args.evaluation_interval == 0:
        dqn.eval()  # Set DQN (policy network) to evaluation mode
        avg_reward, avg_Q = test(args, T, dqn, val_mem)  # Test
        print('Evaluation @ T=' + str(T) + ' | Avg. reward: ' + str(avg_reward) + ' | Avg. Q: ' + str(avg_Q))
        dqn.train()  # Set DQN (policy network) back to training mode

    # Update target network
    if T % args.target_update == 0:
      dqn.update_target_net()

    state = Variable(next_state)

env.close()
