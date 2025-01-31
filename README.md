# dispel4py

dispel4py is a free and open-source Python library for describing abstract stream-based workflows for distributed data-intensive applications. It enables users to focus on their scientific methods, avoiding distracting details and retaining flexibility over the computing infrastructure they use.  It delivers mappings to diverse computing infrastructures, including cloud technologies, HPC architectures and  specialised data-intensive machines, to move seamlessly into production with large-scale data loads. The dispel4py system maps workflows dynamically onto multiple enactment systems, and supports parallel processing on distributed memory systems with MPI and shared memory systems with multiprocessing, without users having to modify their workflows.

## Dependencies

dispel4py has been tested with Python *2.7.6*, *2.7.5*, *2.7.2*, *2.6.6* and Python *3.4.3*, *3.6*, *3.7*, *3.10*.

The dependencies required for running dispel4py are listed in the requirements.txt file. To install them, please run:
```shell
pip install -r requirements.txt
```

You will also need the following installed on your system:

- If using the MPI mapping, please install [mpi4py](http://mpi4py.scipy.org/)
- If using the Redis mapping, please install [redis](https://redis.io/download/)

## Installation

In order to install dispel4py on your system:

- Clone the git repository
- Make sure that `redis` and the `mpi4py` Python package are installed on your system
- It is optional but recommended to create a virtual environment for dispel4py. Please refer to instructions bellow for setting it up with Conda.
- Install the requirements by running: `pip install -r requirements.txt`
- Run the dispel4py setup script: `python setup.py install`
- Run dispel4py using one of the following commands:
  - `dispel4py <mapping name> <workflow file> <args>`, OR
  - `python -m dispel4py.new.processor <mapping module> <workflow module> <args>`
- See "Examples" section bellow for more details

### Conda Environment

For installing for development with a conda environment, please run the following commands in your terminal.

1. `conda create --name py310 python=3.10`
2. `conda activate py310`
3. `pip uninstall py310`
4. `git clone https://github.com/dispel4py2-0/dispel4py.git`
5. `cd dispel4py`
6. `pip install -r requirements.txt`
7. `python setup.py install`


## Docker

The Dockerfile in the dispel4py root directory builds a Debian Linux distribution and installs dispel4py and OpenMPI.

```
docker build . -t dare-dispel4py
```

Start a Docker container with the dispel4py image in interactive mode with a bash shell:

```
docker run -it dare-dispel4py /bin/bash
```

For the EPOS use cases obspy is included in a separate Dockerfile `Dockerfile.seismo`:

```
docker build . -f Dockerfile.seismo -t dare-dispel4py-seismo
```


## Examples

Some simple examples, intended for testing, are included in this repository.
For more complex "real-world" examples for specific scientific domains, such as seismology, please see:
https://github.com/rosafilgueira/dispel4py_workflows

### Word Count Example

#### Simple mapping

```shell
python -m dispel4py.new.processor dispel4py.new.simple_process dispel4py.examples.graph_testing.word_count -i 10
```

#### Multi mapping

```shell
python -m dispel4py.new.processor dispel4py.new.multi_process dispel4py.examples.graph_testing.word_count -n 5 -i 10
```

#### MPI Mapping
```shell
mpiexec -n 10 python -m dispel4py.new.processor dispel4py.new.mpi_process dispel4py.examples.graph_testing.word_count -i 20 -n 10
```

#### Redis mapping

RDD:
```shell
python -m dispel4py.new.processor dispel4py.new.dynamic_redis dispel4py.examples.graph_testing.word_count -ri localhost -n 4 -i 10
```

Note: In another tab, we need to have REDIS working in background:
```shell
redis-server
```

### Pipeline Test

#### Simple mapping

```shell
python -m dispel4py.new.processor dispel4py.new.simple_process dispel4py.examples.graph_testing.pipeline_test -i 10
```

#### Multi mapping

```shell
python -m dispel4py.new.processor dispel4py.new.multi_process dispel4py.examples.graph_testing.pipeline_test -n 5 -i 10
```

#### MPI Mapping
```shell
mpiexec -n 10 python -m dispel4py.new.processor dispel4py.new.mpi_process dispel4py.examples.graph_testing.pipeline_test -i 20 -n 10
```

### Sentiment Analysis

- Clone this repo: https://github.com/rosafilgueira/dispel4py_workflows/tree/master/twitter_sentiment
- From the main directory of the example (`twitter_sentiment`), run:

#### Simple mapping
```shell
dispel4py simple analysis_sentiment.py  -d '{"read":[{"input":"Articles_cleaned.csv"}]}' 
```

#### Multi mapping
```shell
dispel4py multi analysis_sentiment.py -n 15  -d '{"read":[{"input":"Articles_cleaned.csv"}]}' 
```

#### MPI mapping
```shell
mpiexec -np 15 dispel4py mpi analysis_sentiment.py -d '{"read":[{"input":"Articles_cleaned.csv"}]}'
```

## Contributing

### Code Style

This project is using the `black` package for automatic formatting of Python code. However, there is a lot of old code that may need to be reformatted manually.

For more info, see: https://github.com/psf/black

### Linting

This project uses `ruff` for code linting. See: https://docs.astral.sh/ruff/

Ruff rules are configured and documented in the pyproject.toml file.
Future contributors are encouraged to lint their code using `ruff check .` before contributing and to help fix existing lint errors!

### CI

Some regression testing has been set up to compare the output of the current version of dispel4py with an older version. These tests currently fail, probably due to slightly different formatting and line order.

---
