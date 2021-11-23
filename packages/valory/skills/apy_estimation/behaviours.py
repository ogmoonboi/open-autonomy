# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This module contains the behaviours for the APY estimation skill."""
from abc import ABC
from typing import Dict, Generator, Set, Tuple, Type, Union, cast

from aea.helpers.ipfs.base import IPFSHashOnly

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseState,
)
from packages.valory.skills.abstract_round_abci.utils import BenchmarkTool
from packages.valory.skills.apy_estimation.models import APYParams, SharedState
from packages.valory.skills.apy_estimation.payloads import FetchingPayload
from packages.valory.skills.apy_estimation.rounds import (
    APYEstimationAbciApp,
    CollectHistoryRound,
    PeriodState,
    TransformRound, ResetRound,
)
from packages.valory.skills.apy_estimation.tools.general import gen_unix_timestamps, create_pathdirs, list_to_json_file
from packages.valory.skills.apy_estimation.tools.queries import (
    block_from_timestamp_q,
    eth_price_usd_q,
    pairs_q,
    top_n_pairs_q,
)
from packages.valory.skills.price_estimation_abci.payloads import EstimatePayload
from packages.valory.skills.price_estimation_abci.rounds import EstimateConsensusRound
from packages.valory.skills.simple_abci.behaviours import (
    RegistrationBehaviour,
    TendermintHealthcheckBehaviour,
)

benchmark_tool = BenchmarkTool()


class APYEstimationBaseState(BaseState, ABC):
    """Base state behaviour for the price estimation skill."""

    @property
    def period_state(self) -> PeriodState:
        """Return the period state."""
        return cast(PeriodState, cast(SharedState, self.context.state).period_state)

    @property
    def params(self) -> APYParams:
        """Return the params."""
        return cast(APYParams, self.context.params)


class EmptyResponseError(Exception):
    """Exception for empty response."""


class FetchBehaviour(APYEstimationBaseState):
    """Observe historical data."""

    state_id = "fetch"
    matching_round = CollectHistoryRound

    def setup(self) -> None:
        """Set the behaviour up."""
        create_pathdirs(self.params.history_save_path)

    def _handle_response(
        self, res: Dict, res_context: str, keys: Tuple[Union[str, int], ...]
    ) -> None:
        """Handle a response from a subgraph.

        :param res: the response to handle.
        :param res_context: the context of the current response.
        """
        if res is None:
            self.context.logger.error(
                f"Could not get {res_context} from {self.context.spooky_subgraph.api_id}"
            )

            self.context.spooky_subgraph.increment_retries()
            yield from self.sleep(self.params.sleep_time)
            raise EmptyResponseError()

        value = res[keys[0]]
        if len(keys):
            for key in keys[1:]:
                value = value[key]

        self.context.logger.info(f"Retrieved {res_context}: {value}.")
        self.context.spooky_subgraph.reset_retries()

    def async_act(self) -> Generator:
        """
        Do the action.

        Steps:
        - Ask the configured API the historical data until now, for the configured duration.
        - If the request fails, retry until max retries are exceeded.
        - Send an observation transaction and wait for it to be mined.
        - Wait until ABCI application transitions to the next round.
        - Go to the next behaviour state (set done event).
        """
        if self.context.spooky_subgraph.is_retries_exceeded():
            # now we need to wait and see if the other agents progress the round
            with benchmark_tool.measure(
                self,
            ).consensus():
                yield from self.wait_until_round_end()
            self.set_done()

        else:
            with benchmark_tool.measure(
                self,
            ).local():
                # Fetch top n pool ids.
                spooky_api_specs = self.context.spooky_subgraph.get_spec()
                spooky_needed_specs = {
                    "method": spooky_api_specs["method"],
                    "url": spooky_api_specs["url"],
                    "headers": spooky_api_specs["headers"],
                }

                res_raw = yield from self.get_http_response(
                    content=top_n_pairs_q(self.context.spooky_subgraph.top_n_pools),
                    **spooky_needed_specs,
                )
                res = self.context.spooky_subgraph.process_response(res_raw)

                try:
                    self._handle_response(
                        res,
                        res_context=f"top {self.context.spooky_subgraph.top_n_pools} pool ids (Showing first example)",
                        keys=("pairs", 0, "id"),
                    )
                except EmptyResponseError:
                    return

                pair_ids = [pair["id"] for pair in res["pairs"]]

                pairs_hist = []
                for timestamp in gen_unix_timestamps(self.params.history_duration):

                    # Fetch block.
                    fantom_api_specs = self.context.fantom_subgraph.get_spec()
                    res_raw = yield from self.get_http_response(
                        method=fantom_api_specs["method"],
                        url=fantom_api_specs["url"],
                        headers=fantom_api_specs["headers"],
                        content=block_from_timestamp_q(timestamp),
                    )
                    res = self.context.fantom_subgraph.process_response(res_raw)

                    try:
                        self._handle_response(
                            res, res_context="block", keys=("blocks", 0)
                        )
                    except EmptyResponseError:
                        return

                    fetched_block = res["blocks"][0]

                    # Fetch ETH price for block.
                    res_raw = yield from self.get_http_response(
                        content=eth_price_usd_q(
                            self.context.spooky_subgraph.bundle_id,
                            fetched_block["number"],
                        ),
                        **spooky_needed_specs,
                    )
                    res = self.context.spooky_subgraph.process_response(res_raw)

                    try:
                        self._handle_response(
                            res,
                            res_context=f"ETH price for block {fetched_block}",
                            keys=("bundles", 0, "ethPrice"),
                        )
                    except EmptyResponseError:
                        return

                    eth_price = float(res["bundles"][0]["ethPrice"])

                    # Fetch top n pool data for block.
                    res_raw = yield from self.get_http_response(
                        content=pairs_q(fetched_block["number"], pair_ids),
                        **spooky_needed_specs,
                    )
                    res = self.context.spooky_subgraph.process_response(res_raw)

                    try:
                        self._handle_response(
                            res,
                            res_context=f"top {self.context.spooky_subgraph.top_n_pools} "
                            f"pool data for block {fetched_block} (Showing first example)",
                            keys=("pairs", 0),
                        )
                    except EmptyResponseError:
                        return

                    # Add extra fields to the pairs.
                    for i in range(len(res["pairs"])):
                        res["pairs"][i]["for_timestamp"] = timestamp
                        res["pairs"][i]["block_number"] = fetched_block["number"]
                        res["pairs"][i]["block_timestamp"] = fetched_block["timestamp"]
                        res["pairs"][i]["eth_price"] = eth_price

                    pairs_hist.extend(res["pairs"])

            if len(pairs_hist) > 0:
                # Store historical data to a json file.
                list_to_json_file(self.params.history_save_path, pairs_hist)

                # Hash the file.
                hasher = IPFSHashOnly()
                hist_hash = hasher.get(self.params.history_save_path)

                # Pass the hash as a Payload.
                payload = FetchingPayload(
                    self.context.agent_address,
                    hist_hash,
                )

                # Finish behaviour.
                with benchmark_tool.measure(
                    self,
                ).consensus():
                    yield from self.send_a2a_transaction(payload)
                    yield from self.wait_until_round_end()

                self.set_done()


class TransformBehaviour(APYEstimationBaseState):
    """Transform historical data, i.e., convert them to a dataframe and calculate useful metrics, such as the APY."""

    state_id = "transform"
    matching_round = TransformRound

    def async_act(self) -> Generator:
        """Do the action."""
        raise NotImplementedError()


class EstimateBehaviour(APYEstimationBaseState):
    """Estimate APY."""

    state_id = "estimate"
    matching_round = EstimateConsensusRound

    def async_act(self) -> Generator:
        """
        Do the action.

        Steps:
        - Run the script to compute the estimate starting from the shared observations.
        - Build an estimate transaction and send the transaction and wait for it to be mined.
        - Wait until ABCI application transitions to the next round.
        - Go to the next behaviour state (set done event).
        """

        with benchmark_tool.measure(self).local():
            self.context.logger.info(
                "Got estimate of APY for %s: %s",
                # TODO pool_name param,
                self.context.state.period_state.estimate,
            )
            payload = EstimatePayload(
                self.context.agent_address, self.context.state.period_state.estimate
            )

        with benchmark_tool.measure(self).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class ResetBehaviour(APYEstimationBaseState):
    """Reset state."""

    matching_round = ResetRound
    state_id = "reset"
    pause = False

    def async_act(self) -> Generator:
        """Do the action."""
        raise NotImplementedError()


class APYEstimationConsensusBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the APY estimation."""

    initial_state_cls = TendermintHealthcheckBehaviour
    abci_app_cls = APYEstimationAbciApp
    behaviour_states: Set[Type[APYEstimationBaseState]] = {
        TendermintHealthcheckBehaviour,
        RegistrationBehaviour,
        FetchBehaviour,
        TransformBehaviour,
        EstimateBehaviour,
        ResetBehaviour,
    }

    def setup(self) -> None:
        """Set up the behaviour."""
        super().setup()
        benchmark_tool.logger = self.context.logger
