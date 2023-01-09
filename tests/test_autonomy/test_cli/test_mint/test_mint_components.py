# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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

"""Test `mint` command group."""


from typing import Any
from unittest import mock

from aea_test_autonomy.configurations import ETHEREUM_KEY_DEPLOYER
from aea_test_autonomy.docker.base import skip_docker_tests
from aea_test_autonomy.fixture_helpers import registries_scope_class  # noqa: F401
from requests.exceptions import ConnectionError as RequestsConnectionError

from tests.test_autonomy.test_cli.base import BaseCliTest


class DummyContract:
    """Dummy contract"""

    def get_create_unit_event_filter(self, *args: Any, **kwargs: Any) -> None:
        """Dummy method implementation"""

        raise RequestsConnectionError()

    def get_create_transaction(self, *args: Any, **kwargs: Any) -> None:
        """Dummy method implementation"""


@skip_docker_tests
# @pytest.mark.usefixtures("registries_scope_class")
class TestMintProtocol(BaseCliTest):
    """Test `autonomy develop mint protocol` command."""

    cli_options = ("mint", "protocol")

    def setup(self) -> None:
        """Setup test."""
        super().setup()
        self.cli_runner.mix_stderr = False

    def test_mint(
        self,
    ) -> None:
        """Test mint protocol."""

        result = self.run_cli(
            commands=("packages/valory/protocols/acn", str(ETHEREUM_KEY_DEPLOYER)),
        )

        assert result.exit_code == 0, result.output
        assert "Component minted with:" in result.output
        assert "Metadata Hash:" in result.output
        assert "Token ID:" in result.output

    def test_connection_error(
        self,
    ) -> None:
        """Test connection error."""

        with mock.patch(
            "autonomy.chain.mint.transact", side_effect=RequestsConnectionError
        ):
            result = self.run_cli(
                commands=("packages/valory/protocols/acn", str(ETHEREUM_KEY_DEPLOYER)),
            )
            self.cli_runner.mix_stderr = True
            assert result.exit_code == 1, result.output
            assert (
                "Component mint failed with following error; Cannot connect to the given RPC"
                in result.stderr
            )

    def test_fail_token_id_retrieve(
        self,
    ) -> None:
        """Test token id retrieval failure."""

        with mock.patch(
            "autonomy.chain.mint.get_contract", return_value=DummyContract()
        ), mock.patch("autonomy.chain.mint.transact"):

            result = self.run_cli(
                commands=("packages/valory/protocols/acn", str(ETHEREUM_KEY_DEPLOYER)),
            )

            assert result.exit_code == 1, result.output
            assert (
                "Component mint was successful but token ID retrieving failed with following error; "
                "Connection interrupted while waiting for the unitId emit event"
                in result.stderr
            )
