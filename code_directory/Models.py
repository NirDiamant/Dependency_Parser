import math
from torch import nn
import torch
from code_directory.inference import infer_heads


class WordDropout(nn.Module):
    def __init__(self, appearance_count, a=0.25, unk_ind=0):
        super().__init__()
        self.appearance_count = appearance_count
        self.a = float(a)
        self.unk_ind = unk_ind

    def forward(self, word_idx):
        if self.training and self.appearance_count is not None:
            out = word_idx.clone()
            p = self.a / (self.a + self.appearance_count[word_idx.squeeze(0)])
            drop_idx = torch.rand(word_idx.shape[1], requires_grad=False) < p
            out[0][drop_idx] = self.unk_ind
            return out
        return word_idx


class AdditiveAttention(nn.Module):
    def __init__(self, in_dim, hidden_dim=100, dropout=0.1):
        super().__init__()
        self.layer1_head = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Dropout(p=dropout)
        )
        self.layer1_modifier = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Dropout(p=dropout)
        )
        self.out_layer = nn.Linear(hidden_dim, 1)

    def forward(self, q, k):
        q = self.layer1_head(q)
        k = self.layer1_modifier(k)
        q = q.repeat(1, q.shape[1], 1).view(q.shape[0], q.shape[1], q.shape[1], -1)
        q = q.transpose(1, 2)
        k = k.repeat(1, k.shape[1], 1).view(k.shape[0], k.shape[1], k.shape[1], -1)
        out = q + k
        out = torch.tanh(out)
        out = self.out_layer(out).squeeze(3)
        return out


class MultiplicativeAttention(nn.Module):
    def __init__(self, in_dim, hidden_dim=100, dropout=0.1):
        super().__init__()
        self.layer_head = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Dropout(p=dropout)
        )
        self.layer_modifier = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Dropout(p=dropout)
        )

    def forward(self, q, k):
        q = self.layer_head(q)
        k = self.layer_modifier(k)
        k = k.transpose(1, 2)
        out = torch.bmm(q, k)
        return out


class BaseNet(nn.Module):
    def __init__(self, word_vocab_size, tag_vocab_size, appearance_count=None, word_emb_dim=100, tag_emb_dim=100,
                 lstm_hidden_dim=125, mlp_hidden_dim=100, dropout_a=0.25, unk_word_ind=0, device=None):
        super().__init__()
        self.args = {'word_vocab_size': word_vocab_size, 'tag_vocab_size': tag_vocab_size, 'word_emb_dim': word_emb_dim,
                     'tag_emb_dim': tag_emb_dim, 'mlp_hidden_dim': mlp_hidden_dim}
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = device
        self.word_dropout = WordDropout(appearance_count, dropout_a, unk_word_ind)
        self.word_embedding = nn.Embedding(word_vocab_size, word_emb_dim)  # (B, len(sentence))
        self.tag_embedding = nn.Embedding(tag_vocab_size, tag_emb_dim)    # (B, len(sentence))
        self.lstm = nn.LSTM(input_size=word_emb_dim + tag_emb_dim, hidden_size=lstm_hidden_dim, num_layers=2,
                            batch_first=True, bidirectional=True)  # (B, len(sentence), 2 * hidden)
        self.layer1_head = nn.Linear(2 * lstm_hidden_dim, mlp_hidden_dim)  # (B, len(sentence), mlp_hidden_dim)
        self.layer1_modifier = nn.Linear(2 * lstm_hidden_dim, mlp_hidden_dim)  # (B, len(sentence), mlp_hidden_dim)
        self.out_layer = nn.Linear(mlp_hidden_dim, 1)

    def forward(self, word_idx, tag_idx):
        self.word_dropout(word_idx)
        word_embeds = self.word_embedding(word_idx.to(self.device))
        tag_embeds = self.tag_embedding(tag_idx.to(self.device))
        x = torch.cat((word_embeds, tag_embeds), dim=2)
        lstm_out, _ = self.lstm(x)
        vh = self.layer1_head(lstm_out)
        vm = self.layer1_modifier(lstm_out)
        vh = vh.repeat(1, vh.shape[1], 1).view(vh.shape[0], vh.shape[1], vh.shape[1], -1)
        vh = vh.transpose(1, 2)
        vm = vm.repeat(1, vm.shape[1], 1).view(vm.shape[0], vm.shape[1], vm.shape[1], -1)
        out = vh + vm
        out = torch.tanh(out)
        out = self.out_layer(out).squeeze(3)
        out = out[:, :, 1:]
        return out


class AdvancedNet(nn.Module):
    def __init__(self, word_vocab_size, tag_vocab_size, word_emb_dim=100, tag_emb_dim=100,
                 lstm_hidden_dim=125, lstm_dropout=0., lstm_out_dropout=0., attn_type='additive',
                 attn_hidden_dim=100, attn_dropout=0.,
                 appearance_count=None, dropout_a=0.25, unk_word_ind=0,
                 pre_trained_word_embedding=None, freeze_word_embedding=True, device=None):
        self.args = {'word_vocab_size': word_vocab_size, 'tag_vocab_size': tag_vocab_size, 'word_emb_dim': word_emb_dim,
                     'tag_emb_dim': tag_emb_dim, 'attn_type': attn_type, 'attn_hidden_dim': attn_hidden_dim}
        super().__init__()
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = device
        self.word_dropout = WordDropout(appearance_count, dropout_a, unk_word_ind)
        if pre_trained_word_embedding is None:
            self.word_embedding = nn.Embedding(word_vocab_size, word_emb_dim)
        else:
            self.word_embedding = nn.Embedding.from_pretrained(pre_trained_word_embedding, freeze=freeze_word_embedding)
        self.tag_embedding = nn.Embedding(tag_vocab_size, tag_emb_dim)    # (B, len(sentence))
        self.lstm = nn.LSTM(input_size=word_emb_dim + tag_emb_dim, hidden_size=lstm_hidden_dim, num_layers=2,
                            batch_first=True, bidirectional=True, dropout=lstm_dropout)
        self.encoder_dropout = nn.Dropout(p=lstm_out_dropout)
        if attn_type == 'additive':
            self.attn = AdditiveAttention(in_dim=2*lstm_hidden_dim, hidden_dim=attn_hidden_dim, dropout=attn_dropout)
        if attn_type == 'multiplicative':
            self.attn = MultiplicativeAttention(in_dim=2*lstm_hidden_dim, hidden_dim=attn_hidden_dim,
                                                dropout=attn_dropout)

    def forward(self, word_idx, tag_idx):
        self.word_dropout(word_idx)
        word_embeds = self.word_embedding(word_idx.to(self.device))
        tag_embeds = self.tag_embedding(tag_idx.to(self.device))
        x = torch.cat((word_embeds, tag_embeds), dim=2)
        lstm_out, _ = self.lstm(x)
        lstm_out = self.encoder_dropout(lstm_out)
        out = self.attn(q=lstm_out, k=lstm_out)
        return out[:, :, 1:]


class PositionalEncoding(nn.Module):

    def __init__(self, d_model, max_len=300):
        super(PositionalEncoding, self).__init__()

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1)
        self.register_buffer('pe', pe)

    def forward(self, x):
        x = x + self.pe[:x.size(0), :]
        return x


class TransformerModel(nn.Module):
    def __init__(self, word_vocab_size, tag_vocab_size, word_emb_dim=100, tag_emb_dim=100,
                 nhead=8, transformer_hidden=256, transformer_layers=2, transformer_dropout=0.5,
                 attn_type='additive', attn_hidden_dim=100, attn_dropout=0, appearance_count=None,
                 dropout_a=0.25, unk_word_ind=0, pre_trained_word_embedding=None, freeze_word_embedding=True,
                 device=None):
        super().__init__()
        self.inp_dim = word_emb_dim + tag_emb_dim
        self.pos_encoder = PositionalEncoding(word_emb_dim + tag_emb_dim)
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = device
        self.word_dropout = WordDropout(appearance_count, dropout_a, unk_word_ind)
        if pre_trained_word_embedding is None:
            self.word_embedding = nn.Embedding(word_vocab_size, word_emb_dim)
        else:
            self.word_embedding = nn.Embedding.from_pretrained(pre_trained_word_embedding, freeze=freeze_word_embedding)
        self.tag_embedding = nn.Embedding(tag_vocab_size, tag_emb_dim)
        encoding_layer = nn.TransformerEncoderLayer(self.inp_dim, nhead, transformer_hidden, transformer_dropout)
        self.encoder = nn.TransformerEncoder(encoding_layer, transformer_layers)
        if attn_type == 'additive':
            self.attn = AdditiveAttention(in_dim=self.inp_dim, hidden_dim=attn_hidden_dim, dropout=attn_dropout)
        if attn_type == 'multiplicative':
            self.attn = MultiplicativeAttention(in_dim=self.inp_dim, hidden_dim=attn_hidden_dim,
                                                dropout=attn_dropout)

    def forward(self, word_idx, tag_idx):
        sec_len = word_idx.size(1)
        self.word_dropout(word_idx)
        word_embeds = self.word_embedding(word_idx.to(self.device))
        tag_embeds = self.tag_embedding(tag_idx.to(self.device))
        x = torch.cat((word_embeds, tag_embeds), dim=2)
        x = x.transpose(0, 1) * math.sqrt(self.inp_dim)
        x = self.pos_encoder(x)
        encoding = self.encoder(x, mask=torch.zeros((sec_len, sec_len), device=self.device))
        encoding = encoding.transpose(0, 1)
        out = self.attn(q=encoding, k=encoding)
        return out[:, :, 1:]


def nll_loss(out, true_heads):
    sentence_len = true_heads.shape[0]
    true_scores = out[:, true_heads, torch.arange(sentence_len)]
    sum_exp = torch.sum(torch.exp(out), dim=1)
    log_sum_exp = torch.log(sum_exp)
    return torch.mean(- true_scores + log_sum_exp)


def paper_loss(out, true_heads):
    sentence_len = true_heads.shape[0]
    modifiers = torch.arange(sentence_len)
    true_score = torch.sum(out[:, true_heads, modifiers])
    shifted_scores = out + 1
    shifted_scores[:, true_heads, modifiers] -= 1
    inferred_heads = infer_heads(shifted_scores)
    inferred_score = torch.sum(shifted_scores[:, inferred_heads, modifiers])
    loss = torch.max(torch.tensor(0.), inferred_score - true_score + 1)
    return loss


def regularized_paper_loss(out, true_heads, alpha=0.1):
    sentence_len = true_heads.shape[0]
    modifiers = torch.arange(sentence_len)
    true_score = torch.sum(out[:, true_heads, modifiers])
    shifted_scores = out + 1
    shifted_scores[:, true_heads, modifiers] -= 1
    inferred_heads = infer_heads(shifted_scores)
    inferred_score = torch.sum(shifted_scores[:, inferred_heads, modifiers])
    reg = alpha * torch.sum(out[:, true_heads, modifiers]**2)
    loss = torch.max(torch.tensor(0.), inferred_score - true_score + 1) + reg
    return loss


def variational_paper_loss(out, true_heads, std=0.1):
    out = out + torch.normal(mean=0.0, std=std, size=out.shape, device=out.device)
    sentence_len = true_heads.shape[0]
    modifiers = torch.arange(sentence_len)
    true_score = torch.sum(out[:, true_heads, modifiers])
    shifted_scores = out + 1
    shifted_scores[:, true_heads, modifiers] -= 1
    inferred_heads = infer_heads(shifted_scores)
    inferred_score = torch.sum(shifted_scores[:, inferred_heads, modifiers])
    loss = torch.max(torch.tensor(0.), inferred_score - true_score + 1)
    return loss
