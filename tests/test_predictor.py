"""The Hugging Face predictor: what the model is asked, and what reaches Lean.

These cases use a stand-in tokenizer and model so the decoding path can be
checked without loading weights.  The path matters: a completion that only
echoes the prompt must not turn into a Lean call, and a greedy run must not
carry a sampling temperature.
"""
import pytest

torch = pytest.importorskip("torch")

pytestmark = pytest.mark.model


class FakeBatch(dict):
    """A batch that unpacks like a `BatchEncoding` and reads like an object.

    The real tokenizer returns a `BatchEncoding`, which is both a mapping and
    an attribute holder, and the predictor uses it in both ways.
    """

    def __init__(self, input_ids):
        super().__init__(input_ids=input_ids)
        self.input_ids = input_ids


class FakeTokenizer:
    """A tokenizer that records the prompts it is given and decodes by id."""

    eos_token_id = 0

    def __init__(self, stack):
        self.stack = stack
        self.prompts = []

    def __call__(self, text, return_tensors=None, **kwargs):
        self.prompts.append(text)
        ids = list(range(1, 1 + self.stack.prompt_length))
        return FakeBatch(torch.tensor([ids]))

    def decode(self, ids, skip_special_tokens=True):
        if isinstance(ids, torch.Tensor):
            ids = ids.tolist()
        return "\n".join(self.stack.vocab.get(index, "") for index in ids)


class FakeModel:
    """A model that returns fixed completions and records its generation call."""

    def __init__(self, stack):
        self.stack = stack
        self.calls = []

    def eval(self):
        return self

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        prompt_length = kwargs["input_ids"].shape[1]
        rows = []
        for completion in self.stack.completions[:kwargs["num_return_sequences"]]:
            rows.append(list(range(1, 1 + prompt_length)) + self.stack.ids_for(completion))
        width = max(len(row) for row in rows)
        padded = [row + [0] * (width - len(row)) for row in rows]
        return torch.tensor(padded)


class FakeStack:
    """The stand-in model stack, wired the way `load_hf_predictor` wires it."""

    def __init__(self, completions, prompt_length=4):
        self.prompt_length = prompt_length
        self.completions = list(completions)
        self.vocab = {}       # id -> text
        self.text_ids = {}    # text -> id
        self.next_id = 100
        self.tokenizer = FakeTokenizer(self)
        self.model = FakeModel(self)

    def ids_for(self, text):
        ids = []
        for line in text.rstrip("\n").split("\n"):
            if line not in self.text_ids:
                self.text_ids[line] = self.next_id
                self.vocab[self.next_id] = line
                self.next_id += 1
            ids.append(self.text_ids[line])
        return ids


@pytest.fixture
def stack(monkeypatch):
    """Install a stand-in model stack and return the installer."""
    def install(completions, prompt_length=4):
        fake = FakeStack(completions, prompt_length)
        monkeypatch.setattr("transformers.AutoTokenizer.from_pretrained",
                            lambda *args, **kwargs: fake.tokenizer)
        monkeypatch.setattr("transformers.AutoModelForCausalLM.from_pretrained",
                            lambda *args, **kwargs: fake.model)
        return fake

    return install


def a_state():
    from neuralproof.lean.client import ProofState
    return ProofState(theorem="theorem t : True", context="import Lean", goals=("⊢ True",))


def test_the_tactic_of_the_completion_is_the_candidate(stack):
    from neuralproof.models.predictor import load_hf_predictor
    stack(["simp"])
    predictor = load_hf_predictor("model")
    candidates = predictor.predict(a_state(), 1)
    assert [candidate.tactic for candidate in candidates] == ["simp"]


def test_an_echo_only_completion_produces_no_candidate(stack):
    # A base model that only continues the prompt must not turn into a Lean
    # call; the empty candidate is dropped here.
    from neuralproof.models.predictor import load_hf_predictor
    stack(["Context:\nProof state:\n⊢ True\nNext tactic:\n"])
    predictor = load_hf_predictor("model")
    assert predictor.predict(a_state(), 1) == []


def test_the_tactic_after_an_echo_is_still_found(stack):
    from neuralproof.models.predictor import load_hf_predictor
    stack(["Proof state:\n⊢ True\nNext tactic:\nomega\n"])
    predictor = load_hf_predictor("model")
    candidates = predictor.predict(a_state(), 1)
    assert [candidate.tactic for candidate in candidates] == ["omega"]


def test_a_greedy_run_carries_no_temperature(stack):
    # `temperature` only applies to sampling; passing it with greedy
    # decoding is ignored by transformers and warns.
    from neuralproof.models.predictor import load_hf_predictor
    fake = stack(["simp"])
    predictor = load_hf_predictor("model")
    predictor.predict(a_state(), 1)
    call = fake.model.calls[-1]
    assert "temperature" not in call
    assert call["do_sample"] is False
    assert call["num_return_sequences"] == 1


def test_a_sampled_run_carries_a_temperature(stack):
    from neuralproof.models.predictor import load_hf_predictor
    fake = stack(["simp", "rfl"])
    predictor = load_hf_predictor("model")
    predictor.predict(a_state(), 2)
    call = fake.model.calls[-1]
    assert call["temperature"] == pytest.approx(0.8)
    assert call["do_sample"] is True
    assert call["num_return_sequences"] == 2


def test_the_generation_is_bounded(stack):
    from neuralproof.models.predictor import load_hf_predictor
    fake = stack(["simp"])
    predictor = load_hf_predictor("model")
    predictor.predict(a_state(), 1)
    assert fake.model.calls[-1]["max_new_tokens"] == 64


def test_the_model_is_asked_with_the_canonical_prompt(stack):
    from neuralproof.models.prompt import format_tactic_prompt
    from neuralproof.models.predictor import load_hf_predictor
    fake = stack(["simp"])
    predictor = load_hf_predictor("model")
    predictor.predict(a_state(), 1)
    assert fake.tokenizer.prompts == [format_tactic_prompt("import Lean", "⊢ True")]


def test_the_revision_reaches_the_model(stack, monkeypatch):
    from neuralproof.models.predictor import load_hf_predictor
    stack(["simp"])
    seen = {}

    def fake_from_pretrained(model_id, revision=None):
        seen["revision"] = revision
        return FakeStack(["simp"]).model

    monkeypatch.setattr("transformers.AutoModelForCausalLM.from_pretrained", fake_from_pretrained)
    load_hf_predictor("model", revision="abc123")
    assert seen["revision"] == "abc123"


def test_an_adapter_is_loaded_when_one_is_given(stack, monkeypatch):
    pytest.importorskip("peft")
    from neuralproof.models.predictor import load_hf_predictor
    stack(["simp"])
    seen = {}

    def fake_from_pretrained(model, adapter):
        seen["adapter"] = adapter
        return model

    monkeypatch.setattr("peft.PeftModel.from_pretrained", fake_from_pretrained)
    load_hf_predictor("model", adapter="path/to/adapter")
    assert seen["adapter"] == "path/to/adapter"


def test_no_adapter_is_loaded_when_none_is_given(stack, monkeypatch):
    pytest.importorskip("peft")
    from neuralproof.models.predictor import load_hf_predictor
    stack(["simp"])

    def fake_from_pretrained(model, adapter):
        raise AssertionError("the adapter must not be loaded")

    monkeypatch.setattr("peft.PeftModel.from_pretrained", fake_from_pretrained)
    load_hf_predictor("model")


def test_several_candidates_are_returned_in_order(stack):
    from neuralproof.models.predictor import load_hf_predictor
    stack(["simp", "rfl", "omega"])
    predictor = load_hf_predictor("model")
    candidates = predictor.predict(a_state(), 3)
    assert [candidate.tactic for candidate in candidates] == ["simp", "rfl", "omega"]
