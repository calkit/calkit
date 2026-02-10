"""Tests for the ``calkit.matlab`` module."""

import os
import shutil

import pytest

from calkit.matlab import (
    _detect_matlab_io_static,
    detect_matlab_command_io,
    detect_matlab_script_io,
    get_deps_from_matlab,
)


@pytest.mark.skipif(
    shutil.which("matlab") is None, reason="Test requires MATLAB installed"
)
def test_get_deps_from_matlab(tmp_dir):
    """Test getting dependencies from MATLAB using requiredFilesAndProducts."""
    # Create a parent MATLAB script that calls a child function
    child_content = """function matlab_child()
    disp('Hello from child function!');
end
"""
    parent_content = """matlab_child()
"""
    with open("matlab_child.m", "w") as f:
        f.write(child_content)
    with open("matlab_parent.m", "w") as f:
        f.write(parent_content)
    # Get dependencies for the parent script
    deps = get_deps_from_matlab("matlab_parent.m")
    # Should include both parent and child
    assert "matlab_parent.m" in deps
    assert "matlab_child.m" in deps


@pytest.mark.skipif(
    shutil.which("matlab") is None, reason="Test requires MATLAB installed"
)
def test_detect_matlab_script_io(tmp_dir):
    """Test detection of inputs from MATLAB scripts."""
    # Create a parent MATLAB script that calls a child function
    child_content = """function matlab_child()
    disp('Hello from child function!');
end
"""
    parent_content = """matlab_child()
"""
    with open("matlab_child.m", "w") as f:
        f.write(child_content)
    with open("matlab_parent.m", "w") as f:
        f.write(parent_content)
    # Detect I/O for the parent script
    result = detect_matlab_script_io("matlab_parent.m")
    # Check detected inputs
    assert "matlab_parent.m" in result["inputs"]
    assert "matlab_child.m" in result["inputs"]
    # MATLAB cannot detect outputs automatically
    assert result["outputs"] == []


@pytest.mark.skipif(
    shutil.which("matlab") is None, reason="Test requires MATLAB installed"
)
def test_detect_matlab_command_io(tmp_dir):
    """Test detection of inputs from MATLAB commands."""
    # Create a child function that the command will call
    child_content = """function matlab_child()
    disp('Hello from child function!');
end
"""
    with open("matlab_child.m", "w") as f:
        f.write(child_content)
    # Test command detection
    command = "matlab_child(); disp('Done');"
    result = detect_matlab_command_io(command)
    # Check detected inputs (should include the child function)
    assert "matlab_child.m" in result["inputs"]
    # MATLAB cannot detect outputs automatically
    assert result["outputs"] == []
    # Ensure temp file was cleaned up
    temp_files = [f for f in os.listdir(".") if f.endswith(".m")]
    assert len(temp_files) == 1  # Only matlab_child.m should remain
    assert "matlab_child.m" in temp_files


def test_get_deps_from_matlab_fallback(tmp_dir):
    """Test that get_deps_from_matlab uses static fallback when MATLAB unavailable."""
    # Create a dummy .m file
    with open("script.m", "w") as f:
        f.write("disp('hello');")
    # Try to get deps with a non-existent environment
    # This should fail and fall back to static analysis
    deps = get_deps_from_matlab("script.m", environment="nonexistent-env")
    # Should fall back to static analysis (just the script path)
    assert deps == ["script.m"]


def test_detect_matlab_script_io_fallback(tmp_dir):
    """Test that MATLAB script detection returns fallback when MATLAB unavailable."""
    # Create a dummy .m file
    with open("script.m", "w") as f:
        f.write("disp('hello');")
    # Try to detect with a non-existent environment
    result = detect_matlab_script_io("script.m", environment="nonexistent-env")
    # Should fall back to just the script path
    assert result["inputs"] == ["script.m"]
    assert result["outputs"] == []


def test_detect_matlab_command_io_fallback(tmp_dir):
    """Test that MATLAB command detection uses static analysis fallback."""
    # Create a file that the command will reference
    with open("data.csv", "w") as f:
        f.write("col1,col2\n1,2\n")
    # Try to detect with a non-existent environment (forces fallback)
    command = "data = readtable('data.csv'); writetable(data, 'output.csv');"
    result = detect_matlab_command_io(command, environment="nonexistent-env")
    # Should detect I/O via static analysis
    assert "data.csv" in result["inputs"]
    assert "output.csv" in result["outputs"]


def test_detect_matlab_io_static(tmp_dir):
    """Test static analysis of MATLAB code."""
    # Test various I/O operations
    code = """
    % Load data
    data = load('input.mat');
    table = readtable('data.csv');
    img = imread('image.png');

    % Save results
    save('output.mat', 'results');
    writetable(table, 'results.csv');
    imwrite(processed, 'processed.png');

    % Graphics
    saveas(gcf, 'figure.png');
    exportgraphics(gca, 'plot.pdf');
    """
    result = _detect_matlab_io_static(code)
    # Check inputs
    assert "input.mat" in result["inputs"]
    assert "data.csv" in result["inputs"]
    assert "image.png" in result["inputs"]
    # Check outputs
    assert "output.mat" in result["outputs"]
    assert "results.csv" in result["outputs"]
    assert "processed.png" in result["outputs"]
    assert "figure.png" in result["outputs"]
    assert "plot.pdf" in result["outputs"]


def test_detect_matlab_io_static_with_run(tmp_dir):
    """Test static analysis detects run() calls."""
    # Create child script
    with open("helper.m", "w") as f:
        f.write("disp('helper');")
    code = """
    run('helper.m');
    disp('main');
    """
    result = _detect_matlab_io_static(code, ".")
    # Should detect helper.m as input
    assert "helper.m" in result["inputs"]


def test_detect_matlab_io_static_comments(tmp_dir):
    """Test that comments are properly removed during static analysis."""
    code = """
    % load('commented_input.txt');
    %{
    This is a block comment
    load('block_commented.mat');
    %}
    load('actual_input.mat');  % This is real
    """
    result = _detect_matlab_io_static(code)
    # Should only detect the non-commented load
    assert "actual_input.mat" in result["inputs"]
    assert "commented_input.txt" not in result["inputs"]
    assert "block_commented.mat" not in result["inputs"]


def test_detect_matlab_io_static_audio_video(tmp_dir):
    """Test static analysis detects audio and video I/O."""
    code = """
    [audio, fs] = audioread('sound.wav');
    video = VideoReader('movie.mp4');
    audiowrite('output.wav', audio, fs);
    v = VideoWriter('output.avi');
    """
    result = _detect_matlab_io_static(code)
    # Check inputs
    assert "sound.wav" in result["inputs"]
    assert "movie.mp4" in result["inputs"]
    # Check outputs
    assert "output.wav" in result["outputs"]
    assert "output.avi" in result["outputs"]


def test_detect_matlab_script_io_static_fallback(tmp_dir):
    """Test that script detection uses static analysis when MATLAB unavailable."""
    # Create a MATLAB script with I/O operations
    script_content = """
    data = load('input.mat');
    save('output.mat', 'data');
    """
    with open("script.m", "w") as f:
        f.write(script_content)
    # Detect with non-existent environment (forces static analysis)
    result = detect_matlab_script_io("script.m", environment="nonexistent-env")
    # Should include the script itself and detected I/O
    assert "script.m" in result["inputs"]
    assert "input.mat" in result["inputs"]
    assert "output.mat" in result["outputs"]
