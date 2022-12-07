# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022 Valory AG
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

"""Test mint helpers."""

import tempfile
from pathlib import Path
from unittest import mock

from aea.configurations.constants import DEFAULT_README_FILE
from aea.configurations.data_types import PublicId

from autonomy.chain.mint import (
    DEFAULT_NFT_IMAGE_HASH,
    publish_metadata,
    serialize_metadata,
)


DUMMY_HASH = "bafybei0000000000000000000000000000000000000000000000000000"


def test_serialize_metadata() -> None:
    """Test serialize metadata."""
    expected_string = """{"name": "author/name", "description": "Some package", "code_uri": "ipfs://bafybei0000000000000000000000000000000000000000000000000000", "image": "ipfs://bafybeiggnad44tftcrenycru2qtyqnripfzitv5yume4szbkl33vfd4abm", "attributes": [{"trait_type": "version", "value": "latest"}]}"""
    metadata_string = serialize_metadata(
        package_hash=DUMMY_HASH,
        public_id=PublicId(author="author", name="name"),
        description="Some package",
        nft_image_hash=DEFAULT_NFT_IMAGE_HASH,
    )

    assert metadata_string == expected_string


def test_publish_metadata() -> None:
    """Test publish metadata tool with dummy config."""

    expected_hash = "0xd32dbeede9cb89d6fe6fcd1e111b553d922f75cbce3a3e8b669f3d981a8bc30a"
    with mock.patch("autonomy.chain.mint.IPFSHashOnly.get", return_value=DUMMY_HASH):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir)
            (package_path / DEFAULT_README_FILE).write_text("Description")

            metadata_hash = publish_metadata(
                public_id=PublicId(author="author", name="name"),
                package_path=package_path,
                nft_image_hash=DEFAULT_NFT_IMAGE_HASH,
            )

    assert metadata_hash == expected_hash
