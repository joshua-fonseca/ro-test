from screen import fit_size


def test_largest_16_9_that_fits():
    # 1920x1032 usable area (taskbar), 16 px side frame, 39 px title bar + frame
    assert fit_size(1920, 1032, 16, 39) == (1765, 993)  # height-limited
    assert fit_size(3000, 2000, 16, 39) == (2984, 1678)  # width-limited


def test_explicit_sizes_win():
    assert fit_size(1920, 1032, 16, 39, width=1600) == (1600, 900)
    assert fit_size(1920, 1032, 16, 39, height=900) == (1600, 900)
    assert fit_size(1920, 1032, 16, 39, 1500, 1000) == (1500, 1000)
