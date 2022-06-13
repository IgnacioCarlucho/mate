from ray import tune
from ray.rllib.models import MODEL_DEFAULTS
from ray.rllib.policy.policy import PolicySpec

import mate

from examples.i2c.models import I2CModel
from examples.utils import (RLlibMultiAgentAPI, RLlibMultiAgentCentralizedTraining, FrameSkip,
                            ShiftAgentActionTimestep, CustomMetricCallback, RLlibMultiCallbacks,
                            independent_policy_mapping_fn)


def camera_agent_factory():
    return mate.agents.GreedyCameraAgent(seed=0)


def make_env(env_config):
    env_config = env_config or {}
    env_id = env_config.get('env_id', 'MultiAgentTracking-v0')
    base_env = mate.make(env_id, config=env_config.get('config'), **env_config.get('config_overrides', {}))
    if str(env_config.get('enhanced_observation', None)).lower() != 'none':
        base_env = mate.EnhancedObservation(base_env, team=env_config['enhanced_observation'])

    discrete_levels = env_config.get('discrete_levels', None)
    assert discrete_levels is not None, 'I2C only supports discrete actions.'
    base_env = mate.DiscreteTarget(base_env, levels=discrete_levels)

    camera_agent = env_config.get('opponent_agent_factory', camera_agent_factory)()
    env = mate.MultiTarget(base_env, camera_agent=camera_agent)

    env = mate.RelativeCoordinates(env)
    env = mate.RescaledObservation(env)
    env = mate.RepeatedRewardIndividualDone(env)

    if 'reward_coefficients' in env_config:
        env = mate.AuxiliaryTargetRewards(env, coefficients=env_config['reward_coefficients'],
                                          reduction=env_config.get('reward_reduction', 'none'))

    frame_skip = env_config.get('frame_skip', 1)
    if frame_skip > 1:
        env = FrameSkip(env, frame_skip=frame_skip)

    env = RLlibMultiAgentAPI(env)
    env = RLlibMultiAgentCentralizedTraining(env, add_joint_observation=True)
    return env


tune.register_env('mate-i2c.target', make_env)

config = {
    'framework': 'torch',
    'seed': 0,

    # === Environment ===
    'env': 'mate-i2c.target',
    'env_config': {
        'env_id': 'MultiAgentTracking-v0',
        'config': 'MATE-2v4-0.yaml',
        'config_overrides': {'reward_type': 'dense', 'shuffle_entities': False},
        'discrete_levels': 5,
        'frame_skip': 10,
        'enhanced_observation': 'none',
        'opponent_agent_factory': camera_agent_factory,
    },
    'horizon': 500,
    'callbacks': RLlibMultiCallbacks([CustomMetricCallback, ShiftAgentActionTimestep]),

    # === Model ===
    'normalize_actions': True,
    'model': {
        'max_seq_len': 25,
        'custom_model': I2CModel,
        'custom_model_config': {
            **MODEL_DEFAULTS,
            'actor_hiddens': [512, 256],
            'actor_hidden_activation': 'relu',
            'critic_hiddens': [512, 256],
            'critic_hidden_activation': 'relu',
            'lstm_cell_size': 256,
            'max_seq_len': 25,
            'vf_share_layers': False,

            # I2C model parameters
            'message_dim': 64,
            'policy_corr_reg_coeff': 0.01,
            'temperature': 0.1,
            'prior_buffer_size': 100000,
            'prior_percentile': 50,
        }
    },

    # === Policy ===
    'gamma': 0.99,
    'use_critic': True,
    'use_gae': True,
    'clip_param': 0.3,
    'multiagent': {},  # independent policies defined in below

    # === Exploration ===
    'explore': True,
    'exploration_config': {
        'type': 'StochasticSampling'
    },

    # === Replay Buffer & Optimization ===
    'batch_mode': 'truncate_episodes',
    'rollout_fragment_length': 25,
    'train_batch_size': 1024,
    'sgd_minibatch_size': 256,
    'num_sgd_iter': 16,
    'metrics_num_episodes_for_smoothing': 25,
    'grad_clip': None,
    'lr': 5E-4,
    'lr_schedule': [
        (0, 5E-4),
        (4E6, 5E-4),
        (4E6, 1E-4),
        (8E6, 1E-4),
        (8E6, 5E-5),
    ],
    'entropy_coeff': 0.05,
    'entropy_coeff_schedule': [
        (0, 0.05),
        (2E6, 0.01),
        (4E6, 0.001),
        (10E6, 0.0),
    ],
    'vf_clip_param': 10000.0,
}

# Independent policy for each agent (no parameter sharing)
_dummy_env = make_env(config['env_config'])
config['multiagent'].update(
    policies={
        agent_id: PolicySpec(observation_space=None,
                             action_space=None,
                             config=None)
        for agent_id in _dummy_env.agent_ids
    },
    policy_mapping_fn=independent_policy_mapping_fn
)
del _dummy_env
