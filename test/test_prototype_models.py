import importlib

import pytest
import test_models as TM
import torch
from common_utils import cpu_and_gpu, run_on_env_var
from torchvision.prototype import models
from torchvision.prototype.models._api import WeightsEnum, Weights
from torchvision.prototype.models._utils import handle_legacy_interface

run_if_test_with_prototype = run_on_env_var(
    "PYTORCH_TEST_WITH_PROTOTYPE",
    skip_reason="Prototype tests are disabled by default. Set PYTORCH_TEST_WITH_PROTOTYPE=1 to run them.",
)


def _get_original_model(model_fn):
    original_module_name = model_fn.__module__.replace(".prototype", "")
    module = importlib.import_module(original_module_name)
    return module.__dict__[model_fn.__name__]


def _get_parent_module(model_fn):
    parent_module_name = ".".join(model_fn.__module__.split(".")[:-1])
    module = importlib.import_module(parent_module_name)
    return module


def _get_model_weights(model_fn):
    module = _get_parent_module(model_fn)
    weights_name = "_QuantizedWeights" if module.__name__.split(".")[-1] == "quantization" else "_Weights"
    try:
        return next(
            v
            for k, v in module.__dict__.items()
            if k.endswith(weights_name) and k.replace(weights_name, "").lower() == model_fn.__name__
        )
    except StopIteration:
        return None


def _build_model(fn, **kwargs):
    try:
        model = fn(**kwargs)
    except ValueError as e:
        msg = str(e)
        if "No checkpoint is available" in msg:
            pytest.skip(msg)
        raise e
    return model.eval()


@pytest.mark.parametrize(
    "name, weight",
    [
        ("ResNet50_Weights.ImageNet1K_V1", models.ResNet50_Weights.ImageNet1K_V1),
        ("ResNet50_Weights.default", models.ResNet50_Weights.ImageNet1K_V2),
        (
            "ResNet50_QuantizedWeights.default",
            models.quantization.ResNet50_QuantizedWeights.ImageNet1K_FBGEMM_V2,
        ),
        (
            "ResNet50_QuantizedWeights.ImageNet1K_FBGEMM_V1",
            models.quantization.ResNet50_QuantizedWeights.ImageNet1K_FBGEMM_V1,
        ),
    ],
)
def test_get_weight(name, weight):
    assert models.get_weight(name) == weight


@pytest.mark.parametrize(
    "model_fn",
    TM.get_models_from_module(models)
    + TM.get_models_from_module(models.detection)
    + TM.get_models_from_module(models.quantization)
    + TM.get_models_from_module(models.segmentation)
    + TM.get_models_from_module(models.video),
)
def test_naming_conventions(model_fn):
    weights_enum = _get_model_weights(model_fn)
    assert weights_enum is not None
    assert len(weights_enum) == 0 or hasattr(weights_enum, "default")


@pytest.mark.parametrize(
    "model_fn",
    TM.get_models_from_module(models)
    + TM.get_models_from_module(models.detection)
    + TM.get_models_from_module(models.quantization)
    + TM.get_models_from_module(models.segmentation)
    + TM.get_models_from_module(models.video),
)
def test_schema_meta_validation(model_fn):
    classification_fields = ["size", "categories", "acc@1", "acc@5"]
    defaults = {
        "all": ["interpolation", "recipe"],
        "models": classification_fields,
        "detection": ["categories", "map"],
        "quantization": classification_fields + ["backend", "quantization", "unquantized"],
        "segmentation": ["categories", "mIoU", "acc"],
        "video": classification_fields,
    }
    module_name = model_fn.__module__.split(".")[-2]
    fields = set(defaults["all"] + defaults[module_name])

    weights_enum = _get_model_weights(model_fn)

    problematic_weights = {}
    for w in weights_enum:
        missing_fields = fields - set(w.meta.keys())
        if missing_fields:
            problematic_weights[w] = missing_fields

    assert not problematic_weights


@pytest.mark.parametrize("model_fn", TM.get_models_from_module(models))
@pytest.mark.parametrize("dev", cpu_and_gpu())
@run_if_test_with_prototype
def test_classification_model(model_fn, dev):
    TM.test_classification_model(model_fn, dev)


@pytest.mark.parametrize("model_fn", TM.get_models_from_module(models.detection))
@pytest.mark.parametrize("dev", cpu_and_gpu())
@run_if_test_with_prototype
def test_detection_model(model_fn, dev):
    TM.test_detection_model(model_fn, dev)


@pytest.mark.parametrize("model_fn", TM.get_models_from_module(models.quantization))
@run_if_test_with_prototype
def test_quantized_classification_model(model_fn):
    TM.test_quantized_classification_model(model_fn)


@pytest.mark.parametrize("model_fn", TM.get_models_from_module(models.segmentation))
@pytest.mark.parametrize("dev", cpu_and_gpu())
@run_if_test_with_prototype
def test_segmentation_model(model_fn, dev):
    TM.test_segmentation_model(model_fn, dev)


@pytest.mark.parametrize("model_fn", TM.get_models_from_module(models.video))
@pytest.mark.parametrize("dev", cpu_and_gpu())
@run_if_test_with_prototype
def test_video_model(model_fn, dev):
    TM.test_video_model(model_fn, dev)


@pytest.mark.parametrize(
    "model_fn",
    TM.get_models_from_module(models)
    + TM.get_models_from_module(models.detection)
    + TM.get_models_from_module(models.quantization)
    + TM.get_models_from_module(models.segmentation)
    + TM.get_models_from_module(models.video),
)
@pytest.mark.parametrize("dev", cpu_and_gpu())
@run_if_test_with_prototype
def test_old_vs_new_factory(model_fn, dev):
    defaults = {
        "models": {
            "input_shape": (1, 3, 224, 224),
        },
        "detection": {
            "input_shape": (3, 300, 300),
        },
        "quantization": {
            "input_shape": (1, 3, 224, 224),
            "quantize": True,
        },
        "segmentation": {
            "input_shape": (1, 3, 520, 520),
        },
        "video": {
            "input_shape": (1, 3, 4, 112, 112),
        },
    }
    model_name = model_fn.__name__
    module_name = model_fn.__module__.split(".")[-2]
    kwargs = {"pretrained": True, **defaults[module_name], **TM._model_params.get(model_name, {})}
    input_shape = kwargs.pop("input_shape")
    kwargs.pop("num_classes", None)  # ignore this as it's an incompatible speed optimization for pre-trained models
    x = torch.rand(input_shape).to(device=dev)
    if module_name == "detection":
        x = [x]

    # compare with new model builder parameterized in the old fashion way
    try:
        model_old = _build_model(_get_original_model(model_fn), **kwargs).to(device=dev)
        model_new = _build_model(model_fn, **kwargs).to(device=dev)
    except ModuleNotFoundError:
        pytest.skip(f"Model '{model_name}' not available in both modules.")
    torch.testing.assert_close(model_new(x), model_old(x), rtol=0.0, atol=0.0, check_dtype=False)


def test_smoke():
    import torchvision.prototype.models  # noqa: F401


# With this filter, every unexpected warning will be turned into an error
@pytest.mark.filterwarnings("error")
class TestHandleLegacyInterface:
    class TestWeights(WeightsEnum):
        Sentinel = Weights(url="https://pytorch.org", transforms=lambda x: x, meta=dict())

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param(dict(), id="empty"),
            pytest.param(dict(weights=None), id="None"),
            pytest.param(dict(weights=TestWeights.Sentinel), id="Weights"),
        ],
    )
    def test_no_warn(self, kwargs):
        @handle_legacy_interface(weights=("pretrained", self.TestWeights.Sentinel))
        def builder(*, weights=None):
            pass

        builder(**kwargs)

    @pytest.mark.parametrize("pretrained", (True, False))
    def test_pretrained_pos(self, pretrained):
        @handle_legacy_interface(weights=("pretrained", self.TestWeights.Sentinel))
        def builder(*, weights=None):
            pass

        with pytest.warns(UserWarning, match="positional"):
            builder(pretrained)

    @pytest.mark.parametrize("pretrained", (True, False))
    def test_pretrained_kw(self, pretrained):
        @handle_legacy_interface(weights=("pretrained", self.TestWeights.Sentinel))
        def builder(*, weights=None):
            pass

        with pytest.warns(UserWarning, match="deprecated"):
            builder(pretrained)

    @pytest.mark.parametrize("pretrained", (True, False))
    @pytest.mark.parametrize("positional", (True, False))
    def test_equivalent_behavior_weights(self, pretrained, positional):
        @handle_legacy_interface(weights=("pretrained", self.TestWeights.Sentinel))
        def builder(*, weights=None):
            pass

        args, kwargs = ((pretrained,), dict()) if positional else ((), dict(pretrained=pretrained))
        with pytest.warns(UserWarning, match=f"weights={self.TestWeights.Sentinel if pretrained else None}"):
            builder(*args, **kwargs)

    def test_multi_params(self):
        weights_params = ("weights", "weights_other")
        pretrained_params = [param.replace("weights", "pretrained") for param in weights_params]

        @handle_legacy_interface(
            **{
                weights_param: (pretrained_param, self.TestWeights.Sentinel)
                for weights_param, pretrained_param in zip(weights_params, pretrained_params)
            }
        )
        def builder(*, weights=None, weights_other=None):
            pass

        for pretrained_param in pretrained_params:
            with pytest.warns(UserWarning, match="deprecated"):
                builder(**{pretrained_param: True})

    def test_default_callable(self):
        @handle_legacy_interface(
            weights=(
                "pretrained",
                lambda kwargs: self.TestWeights.Sentinel if kwargs["flag"] else None,
            )
        )
        def builder(*, weights=None, flag):
            pass

        with pytest.warns(UserWarning, match="deprecated"):
            builder(pretrained=True, flag=True)

        with pytest.raises(ValueError, match="weights"):
            builder(pretrained=True, flag=False)
