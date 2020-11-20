import numpy as np
import zarr

import hub
from hub.features import Tensor, Image
from hub.utils import Timer


my_schema = {
    "image": Tensor((28, 28, 4), "int32", (28, 28, 4)),
    "label": "<U20",
    "confidence": "float",
}

dynamic_schema = {
    "image": Tensor(shape=(None, None, None), dtype="int32", max_shape=(32, 32, 3)),
    "label": "<U20",
}


def test_pipeline_basic():
    ds = hub.Dataset(
        "./data/test/test_pipeline_basic", mode="w", shape=(100,), schema=my_schema
    )

    for i in range(len(ds)):
        ds["image", i] = np.ones((28, 28, 4), dtype="int32")
        ds["label", i] = f"hello {i}"
        ds["confidence", i] = 0.2

    @hub.transform(schema=my_schema)
    def my_transform(sample, multiplier: int = 2):
        return {
            "image": sample["image"].compute() * multiplier,
            "label": sample["label"].compute(),
            "confidence": sample["confidence"].compute() * multiplier,
        }

    out_ds = my_transform(ds, multiplier=2)
    assert (out_ds["image", 0].compute() == 2).all()
    assert len(list(out_ds)) == 100
    res_ds = out_ds.store("./data/test/test_pipeline_basic_output")

    assert res_ds["label", 5].compute() == "hello 5"
    assert (
        res_ds["image", 4].compute() == 2 * np.ones((28, 28, 4), dtype="int32")
    ).all()
    assert len(res_ds) == len(out_ds)
    assert res_ds.shape[0] == out_ds.shape[0]
    assert "image" in res_ds.schema.dict_ and "label" in res_ds.schema.dict_


def test_pipeline_dynamic():
    ds = hub.Dataset(
        "./data/test/test_pipeline_dynamic3",
        mode="w",
        shape=(1,),
        schema=dynamic_schema,
        cache=False,
    )

    ds["image", 0] = np.ones((30, 32, 3))

    @hub.transform(schema=dynamic_schema)
    def dynamic_transform(sample, multiplier: int = 2):
        return {
            "image": sample["image"].compute() * multiplier,
            "label": sample["label"].compute(),
        }

    out_ds = dynamic_transform(ds, multiplier=4).store(
        "./data/test/test_pipeline_dynamic_output2"
    )

    assert (
        out_ds["image", 0].compute() == 4 * np.ones((30, 32, 3), dtype="int32")
    ).all()


def test_pipeline_multiple():
    ds = hub.Dataset(
        "./data/test/test_pipeline_dynamic3",
        mode="w",
        shape=(1,),
        schema=dynamic_schema,
        cache=False,
    )

    ds["image", 0] = np.ones((30, 32, 3))

    @hub.transform(schema=dynamic_schema, scheduler="threaded", nodes=8)
    def dynamic_transform(sample, multiplier: int = 2):
        return [
            {
                "image": sample["image"].compute() * multiplier,
                "label": sample["label"].compute(),
            }
            for i in range(4)
        ]

    out_ds = dynamic_transform(ds, multiplier=4).store(
        "./data/test/test_pipeline_dynamic_output2"
    )
    assert len(out_ds) == 4
    assert (
        out_ds["image", 0].compute() == 4 * np.ones((30, 32, 3), dtype="int32")
    ).all()


def test_multiprocessing(sample_size=200, width=100, channels=4, dtype="uint8"):

    my_schema = {
        "image": Image(
            (width, width, channels),
            dtype,
            (width, width, channels),
            chunks=(sample_size // 20, width, width, channels),
            compressor="LZ4",
        ),
    }

    with Timer("multiprocesing"):

        @hub.transform(schema=my_schema, scheduler="threaded", nodes=4)
        def my_transform(x):

            a = np.random.random((width, width, channels))
            for i in range(100):
                a *= np.random.random((width, width, channels))

            return {
                "image": (np.ones((width, width, channels), dtype=dtype) * 255),
            }

        ds = hub.Dataset(
            "./data/test/test_pipeline_basic_4",
            mode="w",
            shape=(sample_size,),
            schema=my_schema,
            cache=2 * 26,
        )

        ds_t = my_transform(ds).store("./data/test/test_pipeline_basic_4")

    assert (ds_t["image", :].compute() == 255).all()


def test_pipeline():
    ds = hub.Dataset(
        "./data/test/test_pipeline_multiple", mode="w", shape=(100,), schema=my_schema
    )

    for i in range(len(ds)):
        ds["image", i] = np.ones((28, 28, 4), dtype="int32")
        ds["label", i] = f"hello {i}"
        ds["confidence", i] = 0.2

    with Timer("multiple pipes"):
        @hub.transform(schema=my_schema)
        def my_transform(sample, multiplier: int = 2):
            return {
                "image": sample["image"].compute() * multiplier,
                "label": sample["label"].compute(),
                "confidence": sample["confidence"].compute() * multiplier,
            }

        out_ds = my_transform(ds, multiplier=2)
        out_ds = my_transform(out_ds, multiplier=2)
        out_ds = out_ds.store("./data/test/test_pipeline_multiple_2")

        assert (out_ds["image", 0].compute() == 4).all()

def benchmark(sample_size=100, width=1000, channels=4, dtype="int8"):
    numpy_arr = np.zeros((sample_size, width, width, channels), dtype=dtype)
    zarr_fs = zarr.zeros(
        (sample_size, width, width, channels),
        dtype=dtype,
        store=zarr.storage.FSStore("./data/test/array"),
        overwrite=True,
    )
    zarr_lmdb = zarr.zeros(
        (sample_size, width, width, channels),
        dtype=dtype,
        store=zarr.storage.LMDBStore("./data/test/array2"),
        overwrite=True,
    )

    my_schema = {
        "image": Tensor((width, width, channels), dtype, (width, width, channels)),
    }

    ds_fs = hub.Dataset(
        "./data/test/test_pipeline_basic_3",
        mode="w",
        shape=(sample_size,),
        schema=my_schema,
        cache=0,
    )

    ds_fs_cache = hub.Dataset(
        "./data/test/test_pipeline_basic_2",
        mode="w",
        shape=(sample_size,),
        schema=my_schema,
    )
    if False:
        print(
            f"~~~ Sequential write of {sample_size}x{width}x{width}x{channels} random arrays ~~~"
        )
        for name, arr in [
            ("Numpy", numpy_arr),
            ("Zarr FS", zarr_fs),
            ("Zarr LMDB", zarr_lmdb),
            ("Hub FS", ds_fs["image"]),
            ("Hub FS+Cache", ds_fs_cache["image"]),
        ]:
            with Timer(name):
                for i in range(sample_size):
                    arr[i] = (np.random.rand(width, width, channels) * 255).astype(
                        dtype
                    )

    print(f"~~~ Pipeline {sample_size}x{width}x{width}x{channels} random arrays ~~~")
    for name, processes in [
        ("single", 1),
        ("processed", 10),
    ]:  # , ("ray", 10), ("green", 10), ("dask", 10)]:

        @hub.transform(schema=my_schema, scheduler=name, processes=processes)
        def my_transform(sample):
            return {
                "image": (np.random.rand(width, width, channels) * 255).astype(dtype),
            }

        with Timer(name):
            out_ds = my_transform(ds_fs)
            out_ds.store(f"./data/test/test_pipeline_basic_output_{name}")


if __name__ == "__main__":
    test_pipeline()

    test_multiprocessing()
    test_pipeline_basic()
    test_pipeline_dynamic()
    # benchmark()