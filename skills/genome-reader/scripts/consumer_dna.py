"""Public Python API for genome-reader's consumer-DNA helpers.

Stable, non-underscore re-export surface. Import these instead of reaching
into the private `_common` module:

    import sys
    sys.path.insert(0, "<path-to-genome-reader>/scripts")
    from consumer_dna import iter_consumer_dna, detect_consumer_dna_build
"""

from _common import detect_consumer_dna_build, iter_consumer_dna

__all__ = ["iter_consumer_dna", "detect_consumer_dna_build"]
