# pylint: disable=missing-module-docstring

from typing import Any, Dict, Optional, Tuple, Union

import gym
import numpy as np

from mate import constants as consts
from mate.wrappers.typing import BaseEnvironmentType, WrapperMeta, assert_base_environment


try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


class EnhancedObservation(gym.ObservationWrapper, metaclass=WrapperMeta):
    """Enhance the agent's observation, which sets all observation mask to True.
    The targets can observe the empty status of all warehouses even when far away.
    """

    def __init__(
        self, env: BaseEnvironmentType, team: Literal['both', 'camera', 'target', 'none'] = 'both'
    ) -> None:
        assert_base_environment(env)
        assert team in (
            'both',
            'camera',
            'target',
            'none',
        ), f'Invalid argument team {team!r}. Expect one of {("both", "camera", "target", "none")}.'
        # pylint: disable-next=import-outside-toplevel
        from mate.wrappers.relative_coordinates import RelativeCoordinates

        assert not isinstance(env, RelativeCoordinates), (
            f'You should use wrapper `{self.__class__}` before `RelativeCoordinates`. '
            f'Please check your wrapper order. '
            f'Got env = {env}.'
        )
        # pylint: disable-next=import-outside-toplevel
        from mate.wrappers.rescaled_observation import RescaledObservation

        assert not isinstance(env, RescaledObservation), (
            f'You should use wrapper `{self.__class__}` before `RescaledObservation`. '
            f'Please check your wrapper order. '
            f'Got env = {env}.'
        )

        super().__init__(env)

        self.team = team

        self.enhanced_camera = self.team in ('camera', 'both')
        self.enhanced_target = self.team in ('target', 'both')

        numbers = (env.num_cameras, env.num_targets, env.num_obstacles)
        self.camera_slices = consts.camera_observation_slices_of(*numbers)
        self.target_slices = consts.target_observation_slices_of(*numbers)
        self.target_indices = consts.target_observation_indices_of(*numbers)
        self.target_empty_bits_slice = slice(
            self.target_indices[2] - consts.NUM_WAREHOUSES, self.target_indices[2]
        )

    def load_config(self, config: Optional[Union[Dict[str, Any], str]] = None) -> None:
        """Reinitialize the Multi-Agent Tracking Environment from a dictionary mapping or a JSON/YAML file."""

        self.env.load_config(config=config)

        self.__init__(self.env, team=self.team)

    def observation(
        self, observation: Tuple[np.ndarray, np.ndarray]
    ) -> Tuple[np.ndarray, np.ndarray]:
        if not (self.enhanced_camera or self.enhanced_target):
            return observation

        camera_joint_observation, target_joint_observation = observation

        offset = consts.PRESERVED_DIM
        camera_states_public = camera_joint_observation[
            ..., offset : offset + consts.CAMERA_STATE_DIM_PUBLIC
        ]
        target_states_public = target_joint_observation[
            ..., offset : offset + consts.TARGET_STATE_DIM_PUBLIC
        ]
        camera_states_public_flagged = np.hstack(
            [camera_states_public, np.ones((self.num_cameras, 1))]
        )
        target_states_public_flagged = np.hstack(
            [target_states_public, np.ones((self.num_targets, 1))]
        )
        obstacle_states_flagged = self.obstacle_states_flagged

        if self.enhanced_camera:
            camera_joint_observation[
                ..., self.camera_slices['opponent_states_with_mask']
            ] = target_states_public_flagged.ravel()[np.newaxis, ...]
            camera_joint_observation[
                ..., self.camera_slices['obstacle_states_with_mask']
            ] = obstacle_states_flagged.ravel()[np.newaxis, ...]
            camera_joint_observation[
                ..., self.camera_slices['teammate_states_with_mask']
            ] = camera_states_public_flagged.ravel()[np.newaxis, ...]

        if self.enhanced_target:
            target_joint_observation[..., self.target_empty_bits_slice] = np.logical_not(
                self.remaining_cargoes
            ).all(axis=-1)[np.newaxis, ...]
            target_joint_observation[
                ..., self.target_slices['opponent_states_with_mask']
            ] = camera_states_public_flagged.ravel()[np.newaxis, ...]
            target_joint_observation[
                ..., self.target_slices['obstacle_states_with_mask']
            ] = obstacle_states_flagged.ravel()[np.newaxis, ...]
            target_joint_observation[
                ..., self.target_slices['teammate_states_with_mask']
            ] = target_states_public_flagged.ravel()[np.newaxis, ...]

        return (
            camera_joint_observation.astype(np.float64),
            target_joint_observation.astype(np.float64),
        )

    def __str__(self) -> str:
        return f'<{type(self).__name__}(team={self.team}){self.env}>'
