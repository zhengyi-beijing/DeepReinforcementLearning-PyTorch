import torch
import numpy as np
from Agents.Core.ReplayMemory import ReplayMemory, Transition
from Agents.DDPG.DDPG import DDPGAgent

import pickle


class TDDDPGAgent(DDPGAgent):
    """class for TD3 agents.
            This class contains implementation of TD3 learning. It is derived from DDPG.
            TD3 aims to address the value function overestimation in DDPG through three techniques.
            1) use two Q nets to enable underestimation bias
            2) add target action smoothing to reduce the exploitation of value funciton spikes
            3) update actor net less frequently.
            # Arguments
                config: a dictionary for training parameters
                actors: actor net and its target net
                criticNets: Q net and its target net. Similar to TD3, will have two Q networks
                env: environment for the agent to interact. env should implement same interface of a gym env
                optimizers: network optimizers for both actor net and critic
                netLossFunc: loss function of the network, e.g., mse
                nbAction: number of actions
                stateProcessor: a function to process output from env, processed state will be used as input to the networks
                experienceProcessor: additional steps to process an experience
    """
    def __init__(self, config, actorNets, criticNets, env, optimizers, netLossFunc, nbAction, stateProcessor=None, experienceProcessor = None):

        super(TDDDPGAgent, self).__init__(config, actorNets, criticNets, env, optimizers, netLossFunc, nbAction,
                                               stateProcessor, experienceProcessor)

    def initalizeNets(self, actorNets, criticNets, optimizers):
        self.actorNet = actorNets['actor']
        self.actorNet_target = actorNets['target'] if 'target' in actorNets else None
        self.criticNetOne = criticNets['criticOne']
        self.criticNet_targetOne = criticNets['targetOne'] if 'targetOne' in criticNets else None
        self.criticNetTwo = criticNets['criticTwo']
        self.criticNet_targetTwo = criticNets['targetTwo'] if 'targetTwo' in criticNets else None

        self.actor_optimizer = optimizers['actor']
        self.criticOne_optimizer = optimizers['criticOne']
        self.criticTwo_optimizer = optimizers['criticTwo']

        self.net_to_device()

    def init_memory(self):
        self.memory = ReplayMemory(self.memoryCapacity)


    def read_config(self):
        super(TDDDPGAgent, self).read_config()
        ''''
        Introduce arguments to control actor net update frequency and policy smooth noise
        '''


        self.policyUpdateFreq = 2
        if 'policyUpdateFreq' in self.config:
            self.policyUpdateFreq = self.config['policyUpdateFreq']
        self.policySmoothNoise = 0.01
        if 'policySmoothNoise' in self.config:
            self.policySmoothNoise = self.config['policySmoothNoise']

    def net_to_device(self):
        # move model to correct device
        self.actorNet = self.actorNet.to(self.device)
        self.criticNetOne = self.criticNetOne.to(self.device)
        self.criticNetTwo = self.criticNetTwo.to(self.device)

        # in case targetNet is None
        if self.actorNet_target is not None:
            self.actorNet_target = self.actorNet_target.to(self.device)
        # in case targetNet is None
        if self.criticNet_targetOne is not None:
            self.criticNet_targetOne = self.criticNet_targetOne.to(self.device)
        if self.criticNet_targetTwo is not None:
            self.criticNet_targetTwo = self.criticNet_targetTwo.to(self.device)

    def copy_nets(self):
        '''
        soft update target networks
        '''
        if self.learnStepCounter % self.policyUpdateFreq == 0:
            # update target networks
            for target_param, param in zip(self.actorNet_target.parameters(), self.actorNet.parameters()):
                target_param.data.copy_(param.data * self.tau + target_param.data * (1.0 - self.tau))

            for target_param, param in zip(self.criticNet_targetOne.parameters(), self.criticNetOne.parameters()):
                target_param.data.copy_(param.data * self.tau + target_param.data * (1.0 - self.tau))

            for target_param, param in zip(self.criticNet_targetTwo.parameters(), self.criticNetTwo.parameters()):
                target_param.data.copy_(param.data * self.tau + target_param.data * (1.0 - self.tau))

    def update_net_on_transitions(self, transitions_raw):
        '''
        This function performs gradient gradient on the network
        '''
        state, nonFinalMask, nonFinalNextState, action, reward = self.prepare_minibatch(transitions_raw)

        # Critic loss
        QValuesOne = self.criticNetOne.forward(state, action).squeeze()
        QValuesTwo = self.criticNetTwo.forward(state, action).squeeze()

        actionNoise = torch.randn((nonFinalNextState.shape[0], self.numAction), dtype=torch.float32, device=self.device)
        next_actions = self.actorNet_target.forward(nonFinalNextState) + actionNoise * self.policySmoothNoise

        # next_actions = self.actorNet_target.forward(nonFinalNextState)

        QNext = torch.zeros(self.trainBatchSize, device=self.device, dtype=torch.float32)
        QNextCriticOne = self.criticNet_targetOne.forward(nonFinalNextState, next_actions.detach()).squeeze()
        QNextCriticTwo = self.criticNet_targetTwo.forward(nonFinalNextState, next_actions.detach()).squeeze()

        QNext[nonFinalMask] = torch.min(QNextCriticOne, QNextCriticTwo)

        targetValues = reward + self.gamma * QNext

        criticOne_loss = self.netLossFunc(QValuesOne, targetValues)
        criticTwo_loss = self.netLossFunc(QValuesTwo, targetValues)

        self.criticOne_optimizer.zero_grad()
        self.criticTwo_optimizer.zero_grad()

        # https://jdhao.github.io/2017/11/12/pytorch-computation-graph/
        criticOne_loss.backward(retain_graph=True)
        criticTwo_loss.backward()

        if self.netGradClip is not None:
            torch.nn.utils.clip_grad_norm_(self.criticNetOne.parameters(), self.netGradClip)
            torch.nn.utils.clip_grad_norm_(self.criticNetTwo.parameters(), self.netGradClip)

        self.criticOne_optimizer.step()
        self.criticTwo_optimizer.step()

        if self.learnStepCounter % self.policyUpdateFreq:
            # Actor loss
            # we try to maximize criticNet output(which is state value)
            policy_loss = -self.criticNetOne.forward(state, self.actorNet.forward(state)).mean()

            # update networks
            self.actor_optimizer.zero_grad()
            policy_loss.backward()
            if self.netGradClip is not None:
                torch.nn.utils.clip_grad_norm_(self.actorNet.parameters(), self.netGradClip)

            self.actor_optimizer.step()

            if self.globalStepCount % self.lossRecordStep == 0:
                self.losses.append([self.globalStepCount, self.epIdx, criticOne_loss.item(), criticTwo_loss.item(),
                                    policy_loss.item()])


    def save_all(self, identifier=None):
        if identifier is None:
            identifier = self.identifier
        prefix = self.dirName + identifier + 'Finalepoch' + str(self.epIdx)
        self.saveLosses(prefix + '_loss.txt')
        self.saveRewards(prefix + '_reward.txt')
        with open(prefix + '_memory.pickle', 'wb') as file:
            pickle.dump(self.memory, file)

        torch.save({
            'epoch': self.epIdx,
            'globalStep': self.globalStepCount,
            'actorNet_state_dict': self.actorNet.state_dict(),
            'criticNetOne_state_dict': self.criticNetOne.state_dict(),
            'criticNetTwo_state_dict': self.criticNetTwo.state_dict(),
            'actor_optimizer_state_dict': self.actor_optimizer.state_dict(),
            'criticOne_optimizer_state_dict': self.criticOne_optimizer.state_dict(),
            'criticTwo_optimizer_state_dict': self.criticOne_optimizer.state_dict()
        }, prefix + '_checkpoint.pt')

    def save_checkpoint(self, identifier=None):
        if identifier is None:
            identifier = self.identifier
        prefix = self.dirName + identifier + 'Epoch' + str(self.epIdx)
        self.saveLosses(prefix + '_loss.txt')
        self.saveRewards(prefix + '_reward.txt')
        with open(prefix + '_memory.pickle', 'wb') as file:
            pickle.dump(self.memory, file)

        torch.save({
            'epoch': self.epIdx,
            'globalStep': self.globalStepCount,
            'actorNet_state_dict': self.actorNet.state_dict(),
            'criticNetOne_state_dict': self.criticNetOne.state_dict(),
            'criticNetTwo_state_dict': self.criticNetTwo.state_dict(),
            'actor_optimizer_state_dict': self.actor_optimizer.state_dict(),
            'criticOne_optimizer_state_dict': self.criticOne_optimizer.state_dict(),
            'criticTwo_optimizer_state_dict': self.criticTwo_optimizer.state_dict()
        }, prefix + '_checkpoint.pt')

    def load_checkpoint(self, prefix):
        self.loadLosses(prefix + '_loss.txt')
        self.loadRewards(prefix + '_reward.txt')
        with open(prefix + '_memory.pickle', 'rb') as file:
            self.memory = pickle.load(file)

        checkpoint = torch.load(prefix + '_checkpoint.pt')
        self.epIdx = checkpoint['epoch']
        self.globalStepCount = checkpoint['globalStep']
        self.actorNet.load_state_dict(checkpoint['actorNet_state_dict'])
        self.actorNet_target.load_state_dict(checkpoint['actorNet_state_dict'])
        self.criticNetOne.load_state_dict(checkpoint['criticNetOne_state_dict'])
        self.criticNet_targetOne.load_state_dict(checkpoint['criticNetOne_state_dict'])
        self.criticNetTwo.load_state_dict(checkpoint['criticNetTwo_state_dict'])
        self.criticNet_targetTwo.load_state_dict(checkpoint['criticNetTwo_state_dict'])

        self.actor_optimizer.load_state_dict(checkpoint['actor_optimizer_state_dict'])
        self.criticOne_optimizer.load_state_dict(checkpoint['criticOne_optimizer_state_dict'])
        self.criticTwo_optimizer.load_state_dict(checkpoint['criticTwo_optimizer_state_dict'])