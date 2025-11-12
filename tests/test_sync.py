# VERSION: 0.1.1
import pytest
from unittest.mock import MagicMock, mock_open, patch

# Import the functions to be tested from the main script
import sync

# --- Test Data Fixtures ---

@pytest.fixture
def ideal_model_entry():
    """Returns a correctly formatted model entry for 'test-model-1'."""
    return sync.create_model_entry('test-model-1.gguf')

# --- Unit Tests for Core Logic ---

def test_create_model_entry():
    """Tests that a model entry is created with the correct structure and content."""
    filename = "my-awesome-model.gguf"
    entry = sync.create_model_entry(filename)

    assert entry['name'] == "my awesome model"
    assert "my-awesome-model.gguf" in entry['cmd']
    assert isinstance(entry['cmd'], sync.LiteralString)
    assert 'aliases' in entry

def test_audit_no_changes_for_correct_entry(ideal_model_entry):
    """Tests that the audit function makes no changes when an entry is perfect."""
    config_models = {'test-model-1': ideal_model_entry.copy()}
    updated_count = sync.audit_config_entries(config_models)

    assert updated_count == 0
    assert config_models['test-model-1'] == ideal_model_entry

def test_audit_preserves_manual_changes(ideal_model_entry):
    """Tests that manual changes to fields like 'description' are preserved."""
    manually_edited_entry = ideal_model_entry.copy()
    manually_edited_entry['description'] = "This is a custom user description."
    manually_edited_entry['ttl'] = 120
    manually_edited_entry['cmd'] = "custom command string"

    config_models = {'test-model-1': manually_edited_entry.copy()}
    updated_count = sync.audit_config_entries(config_models)

    assert updated_count == 0
    assert config_models['test-model-1']['description'] == "This is a custom user description."
    assert config_models['test-model-1']['ttl'] == 120
    assert config_models['test-model-1']['cmd'] == "custom command string"

def test_audit_adds_missing_keys_while_preserving_edits(ideal_model_entry):
    """Tests that missing keys are added without overwriting existing manual changes."""
    partial_entry = ideal_model_entry.copy()
    partial_entry['description'] = "Custom description to preserve."
    del partial_entry['ttl']       # Remove a key to be restored
    del partial_entry['aliases']   # Remove another

    config_models = {'test-model-1': partial_entry}
    updated_count = sync.audit_config_entries(config_models)

    assert updated_count == 1
    final_entry = config_models['test-model-1']

    assert final_entry['description'] == "Custom description to preserve."
    assert 'ttl' in final_entry
    assert final_entry['ttl'] == 0
    assert 'aliases' in final_entry
    assert final_entry['aliases'] == []

def test_save_config_wraps_cmd_in_literalstring():
    """Tests that the save_config function correctly wraps 'cmd' before dumping."""
    config_data = {
        'models': {
            'test-model-1': {
                'name': 'Test Model',
                'cmd': 'this is a plain string'
            }
        }
    }
    # Mock yaml.dump to inspect the data it receives
    with patch('sync.yaml.dump') as mock_dump:
        # Mock open and os.replace to isolate the save logic
        with patch('builtins.open', mock_open()) as mock_file:
            with patch('sync.os.replace') as mock_replace:
                sync.save_config('fake_path.yaml', config_data, dry_run=False)

                # Check that dump was called
                mock_dump.assert_called_once()
                # Get the data that was passed to dump
                dumped_data = mock_dump.call_args[0][0]
                # Assert that the 'cmd' field is now a LiteralString instance
                cmd_field = dumped_data['models']['test-model-1']['cmd']
                assert isinstance(cmd_field, sync.LiteralString)
                assert cmd_field == 'this is a plain string'

def test_sync_adds_new_model(ideal_model_entry):
    """Tests that a model found on disk but not in config is added."""
    config_models = {}
    disk_keys = {'test-model-1'}
    
    sync.create_model_entry = MagicMock(return_value=ideal_model_entry)
    
    added, removed = sync.sync_disk_to_config(config_models, disk_keys, prune=False)

    assert added == 1
    assert removed == 0
    assert 'test-model-1' in config_models
    assert config_models['test-model-1'] == ideal_model_entry
    sync.create_model_entry.assert_called_once_with('test-model-1.gguf')

def test_sync_removes_stale_model_with_prune(ideal_model_entry):
    """Tests that a model in config but not on disk is removed when prune=True."""
    config_models = {'stale-model': ideal_model_entry}
    disk_keys = set()

    added, removed = sync.sync_disk_to_config(config_models, disk_keys, prune=True)

    assert added == 0
    assert removed == 1
    assert 'stale-model' not in config_models