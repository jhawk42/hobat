#!/usr/bin/env python3
"""Wrapper script to profile td_webserver.py with cProfile."""

import sys
import cProfile
import pstats
import io
from td_webserver import main


def profile_main():
    """Run td_webserver.main() under cProfile."""
    profiler = cProfile.Profile()
    profiler.enable()
    
    try:
        result = main(sys.argv[1:])
    finally:
        profiler.disable()
    
    # Save profile to file
    prof_path = 'profile_td_webserver.prof'
    profiler.dump_stats(prof_path)
    print(f"\n[Profile saved to {prof_path}]", file=sys.stderr)
    
    # Print stats summary to console
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(20)  # Print top 20 functions
    print(s.getvalue(), file=sys.stderr)
    
    return result


if __name__ == "__main__":
    sys.exit(profile_main())
