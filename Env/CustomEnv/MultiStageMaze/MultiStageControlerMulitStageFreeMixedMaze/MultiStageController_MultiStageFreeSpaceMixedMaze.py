from Agents.StackedDQN.StackedDQN import StackedDQNAgent
from Agents.MultistageController.MultiStageController import MultiStageStackedController
from Env.CustomEnv.MultiStageMaze.MultiStageFreeMaze import CooperativeSimpleMazeTwoDMixed
from Env.CustomEnv.DynamicMaze.DynamicMaze import DynamicMaze, TrajRecorder
from utils.netInit import xavier_init
from Agents.SAC.SACMultiStageUnit import SACMultiStageUnit
from Agents.DQN.DQNMultiStageUnit import DQNMultiStageUnit
from Agents.DQN.DQNA3C import DQNA3CMaster, SharedAdam
import json
from torch import optim
from copy import deepcopy
import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
import math
import os

torch.manual_seed(1)
import torch.nn.functional as F
torch.set_num_threads(1)



from Agents.DQN.DQN import DQNAgent
from Agents.Core.MLPNet import MultiLayerNetRegression
import json
from torch import optim
from copy import deepcopy
from Env.CustomEnv.SimpleMazeTwoD import SimpleMazeTwoD
import numpy as np
import matplotlib.pyplot as plt
import torch

torch.manual_seed(2)
from torch.distributions import Normal


class ValueNet(nn.Module):
    def __init__(self, input_size, hidden_size):
        super(ValueNet, self).__init__()
        self.linear1 = nn.Linear(input_size, hidden_size)
        self.linear2 = nn.Linear(hidden_size, hidden_size)
        self.linear3 = nn.Linear(hidden_size, 1)
        self.apply(xavier_init)


    def forward(self, state):
        """
        Params state and actions are torch tensors
        """

        x = F.relu(self.linear1(state))
        x = F.relu(self.linear2(x))
        value = self.linear3(x)

        return value

class QNet(nn.Module):
    def __init__(self, input_size, hidden_size):
        super(QNet, self).__init__()
        self.linear1 = nn.Linear(input_size, hidden_size)
        self.linear2 = nn.Linear(hidden_size, hidden_size)
        self.linear3 = nn.Linear(hidden_size, 1)
        self.apply(xavier_init)
    def forward(self, state, action):
        """
        Params state and actions are torch tensors
        """
        x = torch.cat([state, action], 1)
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        value = self.linear3(x)

        return value



class GaussianPolicy(nn.Module):
    def __init__(self, num_inputs,  hidden_dim, num_actions,log_sig_min = -20, log_sig_max = 1, epsilon = 1e-6):
        super(GaussianPolicy, self).__init__()

        self.linear1 = nn.Linear(num_inputs, hidden_dim)
        self.linear2 = nn.Linear(hidden_dim, hidden_dim)

        self.mean_linear = nn.Linear(hidden_dim, num_actions)
        self.log_std_linear = nn.Linear(hidden_dim, num_actions)

        self.log_sig_min = log_sig_min
        self.log_sig_max = log_sig_max

        self.epsilon = epsilon

        self.apply(xavier_init)

    def forward(self, state):
        x = F.relu(self.linear1(state))
        x = F.relu(self.linear2(x))
        mean = self.mean_linear(x)
        log_std = self.log_std_linear(x)
        log_std = torch.clamp(log_std, min=self.log_sig_min, max=self.log_sig_max)
        return mean, log_std

    def select_action(self, state, noiseFlag = True, probFlag=False):
        mean, log_std = self.forward(state)
        if not noiseFlag:
            return torch.tanh(mean)  # action is between -1 and 1

        std = log_std.exp()
        normal = Normal(mean, std)
        x_t = normal.rsample()  # for reparameterization trick (mean + std * N(0,1))
        action = torch.tanh(x_t)
        if not probFlag:
            return action

        log_prob = normal.log_prob(x_t)
        # Enforcing Action Bound. Note that derivative of tanh(x) is 1 - tanh(x)^2
        log_prob -= torch.log(1 - action.pow(2) + self.epsilon)
        log_prob = log_prob.sum(1, keepdim=True)
        return action, log_prob



# first construct the neutral network
config = dict()

config['trainStep'] = 1500
config['epsThreshold'] = 0.5
config['epsilon_start'] = 0.5
config['epsilon_final'] = 0.05
config['epsilon_decay'] = 500
config['episodeLength'] = 100
config['numStages'] = 2
config['targetNetUpdateStep'] = 10
config['memoryCapacity'] = 10000
config['trainBatchSize'] = 64
config['gamma'] = 0.99
config['learningRate'] = 0.0001
config['actorLearningRate'] = 0.0001
config['softQLearningRate'] = 0.0001
config['valueLearningRate'] = 0.0001
config['SACAlpha'] = 0.01
config['tau'] = 0.01
config['netGradClip'] = 1
config['logFlag'] = False
config['logFileName'] = 'SimpleMazeLog/traj'
config['logFrequency'] = 500
config['priorityMemoryOption'] = False
config['netUpdateOption'] = 'targetNet'
config['netUpdateFrequency'] = 1
config['priorityMemory_absErrUpper'] = 5
config['device'] = 'cpu'
config['mapWidth'] = 5
config['mapHeight'] = 5

env = CooperativeSimpleMazeTwoDMixed(config)
N_S = env.stateDim
N_A = env.nbActions

# def stateProcessor(state, device = 'cpu'):
#     # given a list a dictions like { 'sensor': np.array, 'target': np.array}
#     # we want to get a diction like {'sensor': list of torch tensor, 'target': list of torch tensor}
#     nonFinalMask = torch.tensor(tuple(map(lambda s: s is not None, state)), device=device, dtype=torch.uint8)
#
#     stateList = [item['state'] for item in state if item is not None]
#     nonFinalState = torch.tensor(stateList, dtype=torch.float32, device=device)
#     return nonFinalState, nonFinalMask


agents = []

netParameter = dict()
netParameter['n_feature'] = N_S
netParameter['n_hidden'] = 128
netParameter['n_output'] = N_A[0]

actorNet = GaussianPolicy(netParameter['n_feature'],
                          netParameter['n_hidden'],
                          netParameter['n_output'])

valueNet = ValueNet(netParameter['n_feature'],
                    netParameter['n_hidden'])

valueTargetNet = deepcopy(valueNet)

softQNetOne = QNet(netParameter['n_feature'] + netParameter['n_output'],
                   netParameter['n_hidden'])

softQNetTwo = QNet(netParameter['n_feature'] + netParameter['n_output'],
                   netParameter['n_hidden'])

actorOptimizer = optim.Adam(actorNet.parameters(), lr=config['actorLearningRate'])
valueOptimizer = optim.Adam(valueNet.parameters(), lr=config['valueLearningRate'])
softQOneOptimizer = optim.Adam(softQNetOne.parameters(), lr=config['softQLearningRate'])
softQTwoOptimizer = optim.Adam(softQNetTwo.parameters(), lr=config['softQLearningRate'])

actorNets = {'actor': actorNet}
criticNets = {'softQOne': softQNetOne, 'softQTwo': softQNetTwo, 'value': valueNet, 'valueTarget': valueTargetNet}
optimizers = {'actor': actorOptimizer, 'softQOne': softQOneOptimizer, \
              'softQTwo': softQTwoOptimizer, 'value': valueOptimizer}

agent = SACMultiStageUnit(config, actorNets, criticNets, env, optimizers, torch.nn.MSELoss(reduction='mean'), netParameter['n_output'])

agents.append(agent)

netParameter['n_output'] = N_A[1]
netParameter['n_hidden'] = [128]

policyNet = MultiLayerNetRegression(netParameter['n_feature'],
                                    netParameter['n_hidden'],
                                    netParameter['n_output'])

targetNet = MultiLayerNetRegression(netParameter['n_feature'],
                                    netParameter['n_hidden'],
                                    netParameter['n_output'])
optimizer = optim.Adam(policyNet.parameters(), lr=config['learningRate'])


agent = DQNMultiStageUnit(config, policyNet, targetNet, env, optimizer, torch.nn.MSELoss(reduction='none'), netParameter['n_output'], stateProcessor=None)
agents.append(agent)


controller = MultiStageStackedController(config, agents, env)


policyFlag = True

nPeriods = config['numStages']

if policyFlag:
    n = 0
    policyX = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    policyY = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    value = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    for i in range(policyX.shape[0]):
        for j in range(policyX.shape[1]):
            state = torch.tensor([i / env.lengthScale, \
                                        j / env.lengthScale], dtype=torch.float32)
            policyX[i, j] = controller.agents[n].select_action(state=state, noiseFlag=False)[0]
            policyY[i, j] = controller.agents[n].select_action(state=state, noiseFlag=False)[1]
            stateValue = controller.agents[n].evaluate_state_value(state.unsqueeze(dim=0))
            value[i, j] = stateValue
    np.savetxt('SimpleMazePolicyXBeforeTrain_stage' + str(n) + '.txt', policyX, fmt='%f', delimiter='\t')
    np.savetxt('SimpleMazePolicyYBeforeTrain_stage' + str(n) + '.txt', policyY, fmt='%f', delimiter='\t')

    np.savetxt('SimpleMazeValueBeforeTrain_stage' + str(n) + '.txt', value, fmt='%f', delimiter='\t')

    n = 1
    policy = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    value = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    for i in range(policy.shape[0]):
        for j in range(policy.shape[1]):
            state = torch.tensor([i / env.lengthScale, \
                                        j / env.lengthScale], dtype=torch.float32)
            policy[i, j] = controller.agents[n].select_action(state=state, noiseFlag=False)
            stateValue = controller.agents[n].evaluate_state_value(state.unsqueeze(dim=0))
            value[i, j] = stateValue
    np.savetxt('SimpleMazePolicyBeforeTrain_stage' + str(n) + '.txt', policy, fmt='%f', delimiter='\t')
    np.savetxt('SimpleMazeValueBeforeTrain_stage' + str(n) + '.txt', value, fmt='%f', delimiter='\t')


controller.train()

if policyFlag:
    n = 0
    policyX = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    policyY = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    value = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    for i in range(policyX.shape[0]):
        for j in range(policyX.shape[1]):
            state = torch.tensor([i / env.lengthScale, \
                                        j / env.lengthScale], dtype=torch.float32)
            policyX[i, j] = controller.agents[n].select_action(state=state, noiseFlag=False)[0]
            policyY[i, j] = controller.agents[n].select_action(state=state, noiseFlag=False)[1]
            stateValue = controller.agents[n].evaluate_state_value(state.unsqueeze(dim=0))
            value[i, j] = stateValue
    np.savetxt('SimpleMazePolicyXAfterTrain_stage' + str(n) + '.txt', policyX, fmt='%f', delimiter='\t')
    np.savetxt('SimpleMazePolicyYAfterTrain_stage' + str(n) + '.txt', policyY, fmt='%f', delimiter='\t')

    np.savetxt('SimpleMazeValueAfterTrain_stage' + str(n) + '.txt', value, fmt='%f', delimiter='\t')

    n = 1
    policy = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    value = np.zeros((env.mapHeight * env.numStages, env.mapWidth * env.numStages), dtype=np.float)
    for i in range(policy.shape[0]):
        for j in range(policy.shape[1]):
            state = torch.tensor([i / env.lengthScale, \
                                        j / env.lengthScale], dtype=torch.float32)
            policy[i, j] = controller.agents[n].select_action(state=state, noiseFlag=False)
            stateValue = controller.agents[n].evaluate_state_value(state.unsqueeze(dim=0))
            value[i, j] = stateValue
    np.savetxt('SimpleMazePolicyAfterTrain_stage' + str(n) + '.txt', policy, fmt='%f', delimiter='\t')
    np.savetxt('SimpleMazeValueAfterTrain_stage' + str(n) + '.txt', value, fmt='%f', delimiter='\t')