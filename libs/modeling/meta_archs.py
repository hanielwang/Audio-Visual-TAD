import math

import torch
from torch import nn
from torch.nn import functional as F

from .models import register_meta_arch, make_backbone, make_neck, make_generator
from .blocks import MaskedConv1D, Scale, LayerNorm
from .losses import ctr_giou_loss_1d, sigmoid_focal_loss, binary_logistic_loss
import json
from ..utils import batched_nms
from matplotlib import pyplot
import matplotlib.pyplot as plt
from matplotlib.pyplot import MultipleLocator
import numpy as np


class PtTransformerClsHeadV(nn.Module):
    """
    1D Conv heads for classification
    """
    def __init__(
        self,
        input_dim,
        feat_dim,
        num_classes,
        prior_prob=0.01,
        num_layers=3,
        kernel_size=3,
        act_layer=nn.ReLU,
        with_ln=False,
        empty_cls = []
    ):
        super().__init__()
        self.act = act_layer()

        # build the head
        self.head = nn.ModuleList()
        self.norm = nn.ModuleList()
        for idx in range(num_layers-1):
            if idx == 0:
                in_dim = input_dim
                out_dim = feat_dim
            else:
                in_dim = feat_dim
                out_dim = feat_dim
            self.head.append(
                MaskedConv1D(
                    in_dim, out_dim, kernel_size,
                    stride=1,
                    padding=kernel_size//2,
                    bias=(not with_ln)
                )
            )
            if with_ln:
                self.norm.append(
                    LayerNorm(out_dim)
                )
            else:
                self.norm.append(nn.Identity())

        # classifier
        self.cls_head = MaskedConv1D(
                feat_dim, 97, kernel_size,
                stride=1, padding=kernel_size//2
            )

        # use prior in model initialization to improve stability
        # this will overwrite other weight init
        bias_value = -(math.log((1 - prior_prob) / prior_prob))
        torch.nn.init.constant_(self.cls_head.conv.bias, bias_value)

        # a quick fix to empty categories:
        # the weights assocaited with these categories will remain unchanged
        # we set their bias to a large negative value to prevent their outputs
        empty_cls = []
        if len(empty_cls) > 0:
            bias_value = -(math.log((1 - 1e-6) / 1e-6))
            for idx in empty_cls:
                torch.nn.init.constant_(self.cls_head.conv.bias[idx], bias_value)

    def forward(self, fpn_feats, fpn_masks):
        assert len(fpn_feats) == len(fpn_masks)

        # apply the classifier for each pyramid level
        out_logits = tuple()
        for _, (cur_feat, cur_mask) in enumerate(zip(fpn_feats, fpn_masks)):
            cur_out = cur_feat
            for idx in range(len(self.head)):
                cur_out, _ = self.head[idx](cur_out, cur_mask)
                cur_out = self.act(self.norm[idx](cur_out))
            cur_logits, _ = self.cls_head(cur_out, cur_mask)
            out_logits += (cur_logits, )

        # fpn_masks remains the same
        return out_logits

class PtTransformerClsHeadN(nn.Module):
    """
    1D Conv heads for classification
    """
    def __init__(
        self,
        input_dim,
        feat_dim,
        num_classes,
        prior_prob=0.01,
        num_layers=3,
        kernel_size=3,
        act_layer=nn.ReLU,
        with_ln=False,
        empty_cls = []
    ):
        super().__init__()
        self.act = act_layer()

        # build the head
        self.head = nn.ModuleList()
        self.norm = nn.ModuleList()
        for idx in range(num_layers-1):
            if idx == 0:
                in_dim = input_dim
                out_dim = feat_dim
            else:
                in_dim = feat_dim
                out_dim = feat_dim
            self.head.append(
                MaskedConv1D(
                    in_dim, out_dim, kernel_size,
                    stride=1,
                    padding=kernel_size//2,
                    bias=(not with_ln)
                )
            )
            if with_ln:
                self.norm.append(
                    LayerNorm(out_dim)
                )
            else:
                self.norm.append(nn.Identity())

        # classifier
        self.cls_head = MaskedConv1D(
                feat_dim, 300, kernel_size,
                stride=1, padding=kernel_size//2
            )

        # use prior in model initialization to improve stability
        # this will overwrite other weight init
        bias_value = -(math.log((1 - prior_prob) / prior_prob))
        torch.nn.init.constant_(self.cls_head.conv.bias, bias_value)

        # a quick fix to empty categories:
        # the weights assocaited with these categories will remain unchanged
        # we set their bias to a large negative value to prevent their outputs
        if len(empty_cls) > 0:
            bias_value = -(math.log((1 - 1e-6) / 1e-6))
            for idx in empty_cls:
                torch.nn.init.constant_(self.cls_head.conv.bias[idx], bias_value)

    def forward(self, fpn_feats, fpn_masks):
        assert len(fpn_feats) == len(fpn_masks)

        # apply the classifier for each pyramid level
        out_logits = tuple()
        for _, (cur_feat, cur_mask) in enumerate(zip(fpn_feats, fpn_masks)):
            cur_out = cur_feat
            for idx in range(len(self.head)):
                cur_out, _ = self.head[idx](cur_out, cur_mask)
                cur_out = self.act(self.norm[idx](cur_out))
            cur_logits, _ = self.cls_head(cur_out, cur_mask)
            out_logits += (cur_logits, )

        # fpn_masks remains the same
        return out_logits



class AudioActionnessHead(nn.Module):
    """
    1D Conv heads for classification
    """
    def __init__(
        self,
        input_dim,
        feat_dim,
        fpn_levels,
        num_layers=3,
        kernel_size=3,
        act_layer=nn.ReLU,
        with_ln=False
    ):
        super().__init__()
        self.fpn_levels = fpn_levels
        self.act = act_layer()

        # build the conv head
        self.head = nn.ModuleList()
        self.norm = nn.ModuleList()
        for idx in range(num_layers-1):
            if idx == 0:
                in_dim = input_dim
                out_dim = feat_dim
            else:
                in_dim = feat_dim
                out_dim = feat_dim
            self.head.append(
                MaskedConv1D(
                    in_dim, out_dim, kernel_size,
                    stride=1,
                    padding=kernel_size//2,
                    bias=(not with_ln)
                )
            )
            if with_ln:
                self.norm.append(
                    LayerNorm(out_dim)
                )
            else:
                self.norm.append(nn.Identity())

        self.scale = nn.ModuleList()
        for idx in range(fpn_levels):
            self.scale.append(Scale())

        # segment regression


        # offset for Gaussian conf
        self.conf_head = MaskedConv1D(
                feat_dim, 1, kernel_size,
                stride=1, padding=kernel_size//2
            )     



    def forward(self, fpn_feats, fpn_masks):
        assert len(fpn_feats) == len(fpn_masks)
        assert len(fpn_feats) == self.fpn_levels

        # apply the classifier for each pyramid level
        out_offsets = tuple()
        out_conf = tuple() 


        for l, (cur_feat, cur_mask) in enumerate(zip(fpn_feats, fpn_masks)): #fpn_feats.shape=(2,512,T), T = [2304,1152,576,288,144,72] for all vids
            cur_out = cur_feat


            for idx in range(len(self.head)):#cycle only for build 3 (1D convolutional + layer normal + ReLU) layers
                cur_out, _ = self.head[idx](cur_out, cur_mask) # 1D convolutional layer
                cur_out = self.act(self.norm[idx](cur_out)) # layer normal + ReLU

            cur_conf, _ = self.conf_head(cur_out, cur_mask) # another single 1D conv layer
            out_conf += (F.relu(self.scale[l](cur_conf)), ) # add the activation output (shape=(1,2)) for all pyramid level

        return out_conf



class PtTransformerRegHead(nn.Module):
    """
    Shared 1D Conv heads for regression
    Simlar logic as PtTransformerClsHead with separated implementation for clarity
    """
    def __init__(
        self,
        input_dim,
        feat_dim,
        fpn_levels,
        num_layers=3,
        kernel_size=3,
        act_layer=nn.ReLU,
        with_ln=False
    ):
        super().__init__()
        self.fpn_levels = fpn_levels
        self.act = act_layer()

        # build the conv head
        self.head = nn.ModuleList()
        self.norm = nn.ModuleList()
        for idx in range(num_layers-1):
            if idx == 0:
                in_dim = input_dim
                out_dim = feat_dim
            else:
                in_dim = feat_dim
                out_dim = feat_dim
            self.head.append(
                MaskedConv1D(
                    in_dim, out_dim, kernel_size,
                    stride=1,
                    padding=kernel_size//2,
                    bias=(not with_ln)
                )
            )
            if with_ln:
                self.norm.append(
                    LayerNorm(out_dim)
                )
            else:
                self.norm.append(nn.Identity())

        self.scale = nn.ModuleList()
        for idx in range(fpn_levels):
            self.scale.append(Scale())

        # segment regression
        self.offset_head = MaskedConv1D(
                feat_dim, 2, kernel_size,
                stride=1, padding=kernel_size//2
            )

        # offset for Gaussian conf
        self.conf_head = MaskedConv1D(
                feat_dim, 2, kernel_size,
                stride=1, padding=kernel_size//2
            )     
        '''
        Why using mask? 
           When training with variable length input, we fixed the maximum input sequence length, padded or cropped the input sequences accordingly,
		and added proper masking for all operations in the model. 
		   This is equivalent to training with sliding windows.
		'''


    def forward(self, fpn_feats, fpn_masks):
        assert len(fpn_feats) == len(fpn_masks)
        assert len(fpn_feats) == self.fpn_levels

        # apply the classifier for each pyramid level
        out_offsets = tuple()
        out_conf = tuple() 

        for l, (cur_feat, cur_mask) in enumerate(zip(fpn_feats, fpn_masks)): #fpn_feats.shape=(2,512,T), T = [2304,1152,576,288,144,72] for all vids
            cur_out = cur_feat

            for idx in range(len(self.head)):#cycle only for build 3 (1D convolutional + layer normal + ReLU) layers
                cur_out, _ = self.head[idx](cur_out, cur_mask) # 1D convolutional layer
                cur_out = self.act(self.norm[idx](cur_out)) # layer normal + ReLU

            ##########################################################################################
            cur_offsets, _ = self.offset_head(cur_out, cur_mask) # another single 1D conv layer, out shape = [2, 2, T]
            out_offsets += (F.relu(self.scale[l](cur_offsets)), ) # add the activation output (shape=(1,2)) for all pyramid level

            cur_conf, _ = self.conf_head(cur_out, cur_mask) # another single 1D conv layer
            out_conf += (F.relu(self.scale[l](cur_conf)), ) # add the activation output (shape=(1,2)) for all pyramid level
            ###########################################################################################

        return out_offsets,out_conf



class CrossAttention(nn.Module):
    r"""
    A cross attention layer.
    Parameters:
        query_dim (`int`): The number of channels in the query.
        cross_attention_dim (`int`, *optional*):
            The number of channels in the encoder_hidden_states. If not given, defaults to `query_dim`.
        heads (`int`,  *optional*, defaults to 8): The number of heads to use for multi-head attention.
        dim_head (`int`,  *optional*, defaults to 64): The number of channels in each head.
        dropout (`float`, *optional*, defaults to 0.0): The dropout probability to use.
        bias (`bool`, *optional*, defaults to False):
            Set to `True` for the query, key, and value linear layers to contain a bias parameter.
    """

    def __init__(
        self,
        query_dim,
        cross_attention_dim,
        heads,
        dim_head,
        dropout,
        bias,
        upcast_attention,
        upcast_softmax,
        added_kv_proj_dim,
        norm_num_groups,
        processor
    ):

        super().__init__()
        inner_dim = dim_head * heads
        cross_attention_dim = cross_attention_dim if cross_attention_dim is not None else query_dim
        self.upcast_attention = upcast_attention
        self.upcast_softmax = upcast_softmax

        self.scale = dim_head**-0.5

        self.heads = heads
        # for slice_size > 0 the attention score computation
        # is split across the batch axis to save memory
        # You can set slice_size with `set_attention_slice`
        self.sliceable_head_dim = heads

        self.added_kv_proj_dim = added_kv_proj_dim

        if norm_num_groups is not None:
            self.group_norm = nn.GroupNorm(num_channels=inner_dim, num_groups=norm_num_groups, eps=1e-5, affine=True)
        else:
            self.group_norm = None

        self.to_q = nn.Linear(query_dim, inner_dim, bias=bias)
        self.to_k = nn.Linear(cross_attention_dim, inner_dim, bias=bias)
        self.to_v = nn.Linear(cross_attention_dim, inner_dim, bias=bias)

        if self.added_kv_proj_dim is not None:
            self.add_k_proj = nn.Linear(added_kv_proj_dim, cross_attention_dim)
            self.add_v_proj = nn.Linear(added_kv_proj_dim, cross_attention_dim)

        self.to_out = nn.ModuleList([])
        self.to_out.append(nn.Linear(inner_dim, query_dim))
        self.to_out.append(nn.Dropout(dropout))

        # set attention processor
        processor = processor if processor is not None else CrossAttnProcessor()
        self.set_processor(processor)

    def set_use_memory_efficient_attention_xformers(self, use_memory_efficient_attention_xformers: bool):
        if use_memory_efficient_attention_xformers:
            if self.added_kv_proj_dim is not None:
                # TODO(Anton, Patrick, Suraj, William) - currently xformers doesn't work for UnCLIP
                # which uses this type of cross attention ONLY because the attention mask of format
                # [0, ..., -10.000, ..., 0, ...,] is not supported
                raise NotImplementedError(
                    "Memory efficient attention with `xformers` is currently not supported when"
                    " `self.added_kv_proj_dim` is defined."
                )
            elif not is_xformers_available():
                raise ModuleNotFoundError(
                    "Refer to https://github.com/facebookresearch/xformers for more information on how to install"
                    " xformers",
                    name="xformers",
                )
            elif not torch.cuda.is_available():
                raise ValueError(
                    "torch.cuda.is_available() should be True but is False. xformers' memory efficient attention is"
                    " only available for GPU "
                )
            else:
                try:
                    # Make sure we can run the memory efficient attention
                    _ = xformers.ops.memory_efficient_attention(
                        torch.randn((1, 2, 40), device="cuda"),
                        torch.randn((1, 2, 40), device="cuda"),
                        torch.randn((1, 2, 40), device="cuda"),
                    )
                except Exception as e:
                    raise e

            processor = XFormersCrossAttnProcessor()
        else:
            processor = CrossAttnProcessor()

        self.set_processor(processor)

    def set_attention_slice(self, slice_size):
        if slice_size is not None and slice_size > self.sliceable_head_dim:
            raise ValueError(f"slice_size {slice_size} has to be smaller or equal to {self.sliceable_head_dim}.")

        if slice_size is not None and self.added_kv_proj_dim is not None:
            processor = SlicedAttnAddedKVProcessor(slice_size)
        elif slice_size is not None:
            processor = SlicedAttnProcessor(slice_size)
        elif self.added_kv_proj_dim is not None:
            processor = CrossAttnAddedKVProcessor()
        else:
            processor = CrossAttnProcessor()

        self.set_processor(processor)

    def set_processor(self, processor: "AttnProcessor"):
        self.processor = processor

    def forward(self, hidden_states, encoder_hidden_states=None, attention_mask=None, **cross_attention_kwargs):
        # The `CrossAttention` class can call different attention processors / attention functions
        # here we simply pass along all tensors to the selected processor class
        # For standard processors that are defined here, `**cross_attention_kwargs` is empty
        return self.processor(
            self,
            hidden_states,
            encoder_hidden_states=encoder_hidden_states,
            attention_mask=attention_mask,
            **cross_attention_kwargs,
        )

    def batch_to_head_dim(self, tensor):
        head_size = self.heads
        batch_size, seq_len, dim = tensor.shape
        tensor = tensor.reshape(batch_size // head_size, head_size, seq_len, dim)
        tensor = tensor.permute(0, 2, 1, 3).reshape(batch_size // head_size, seq_len, dim * head_size)
        return tensor

    def head_to_batch_dim(self, tensor):
        head_size = self.heads
        batch_size, seq_len, dim = tensor.shape
        tensor = tensor.reshape(batch_size, seq_len, head_size, dim // head_size)
        tensor = tensor.permute(0, 2, 1, 3).reshape(batch_size * head_size, seq_len, dim // head_size)
        return tensor

    def get_attention_scores(self, query, key, attention_mask=None):
        dtype = query.dtype
        if self.upcast_attention:
            query = query.float()
            key = key.float()

        attention_scores = torch.baddbmm(
            torch.empty(query.shape[0], query.shape[1], key.shape[1], dtype=query.dtype, device=query.device),
            query,
            key.transpose(-1, -2),
            beta=0,
            alpha=self.scale,
        )

        if attention_mask is not None:
            attention_scores = attention_scores + attention_mask

        if self.upcast_softmax:
            attention_scores = attention_scores.float()

        attention_probs = attention_scores.softmax(dim=-1)
        attention_probs = attention_probs.to(dtype)

        return attention_probs

    def prepare_attention_mask(self, attention_mask, target_length):
        head_size = self.heads
        if attention_mask is None:
            return attention_mask

        if attention_mask.shape[-1] != target_length:
            attention_mask = F.pad(attention_mask, (0, target_length), value=0.0)
            attention_mask = attention_mask.repeat_interleave(head_size, dim=0)
        return attention_mask

class CrossAttnProcessor:
    def __call__(self, attn: CrossAttention, hidden_states, encoder_hidden_states=None, attention_mask=None):

        batch_size, sequence_length, _ = hidden_states.shape
        attention_mask = attn.prepare_attention_mask(attention_mask, sequence_length)

        query = attn.to_q(hidden_states)
        query = attn.head_to_batch_dim(query)

        encoder_hidden_states = encoder_hidden_states if encoder_hidden_states is not None else hidden_states
        key = attn.to_k(encoder_hidden_states)
        value = attn.to_v(encoder_hidden_states)
        key = attn.head_to_batch_dim(key)
        value = attn.head_to_batch_dim(value)

        attention_probs = attn.get_attention_scores(query, key, attention_mask)
        hidden_states = torch.bmm(attention_probs, value)
        hidden_states = attn.batch_to_head_dim(hidden_states)

        # linear proj
        hidden_states = attn.to_out[0](hidden_states)
        # dropout
        hidden_states = attn.to_out[1](hidden_states)

        return hidden_states




@register_meta_arch("LocPointTransformer")
class PtTransformer(nn.Module):
    """
        Transformer based model for single stage action localization
    """
    def __init__(
        self,
        backbone_type,         # a string defines which backbone we use
        fpn_type,              # a string defines which fpn we use
        backbone_arch,         # a tuple defines # layers in embed / stem / branch
        scale_factor,          # scale factor between branch layers
        input_dim,             # input feat dim
        max_seq_len,           # max sequence length (used for training)
        max_buffer_len_factor, # max buffer size (defined a factor of max_seq_len)
        n_head,                # number of heads for self-attention in transformer
        n_mha_win_size,        # window size for self attention; -1 to use full seq
        embd_kernel_size,      # kernel size of the embedding network
        embd_dim,              # output feat channel of the embedding network
        embd_with_ln,          # attach layernorm to embedding network
        fpn_dim,               # feature dim on FPN
        fpn_with_ln,           # if to apply layer norm at the end of fpn
        head_dim,              # feature dim for head
        regression_range,      # regression range on each level of FPN
        head_kernel_size,      # kernel size for reg/cls heads
        head_with_ln,          # attache layernorm to reg/cls heads
        use_abs_pe,            # if to use abs position encoding
        use_rel_pe,            # if to use rel position encoding
        num_classes_v,           # number of action classes
        num_classes_n,
        train_cfg,             # other cfg for training
        test_cfg               # other cfg for testing
    ):
        super().__init__()
        # re-distribute params to backbone / neck / head
        self.fpn_strides = [scale_factor**i for i in range(backbone_arch[-1]+1)]
        self.reg_range = regression_range
        assert len(self.fpn_strides) == len(self.reg_range)
        self.scale_factor = scale_factor
        # #classes = num_classes + 1 (background) with last category as background
        # e.g., num_classes = 10 -> 0, 1, ..., 9 as actions, 10 as background
        #self.num_classes = num_classes
        self.num_classes_verb = num_classes_v
        self.num_classes_noun = num_classes_n
        # check the feature pyramid and local attention window size
        self.max_seq_len = max_seq_len
        if isinstance(n_mha_win_size, int):
            self.mha_win_size = [n_mha_win_size]*len(self.fpn_strides)
        else:
            assert len(n_mha_win_size) == len(self.fpn_strides)
            self.mha_win_size = n_mha_win_size
        max_div_factor = 1
        for l, (s, w) in enumerate(zip(self.fpn_strides, self.mha_win_size)):
            stride = s * (w // 2) * 2 if w > 1 else s
            assert max_seq_len % stride == 0, "max_seq_len must be divisible by fpn stride and window size"
            if max_div_factor < stride:
                max_div_factor = stride
        self.max_div_factor = max_div_factor

        # training time config
        self.train_center_sample = train_cfg['center_sample']
        assert self.train_center_sample in ['radius', 'none']
        self.train_center_sample_radius = train_cfg['center_sample_radius']
        self.train_loss_weight = train_cfg['loss_weight']
        self.train_cls_prior_prob = train_cfg['cls_prior_prob']
        self.train_dropout = train_cfg['dropout']
        self.train_droppath = train_cfg['droppath']
        self.train_label_smoothing = train_cfg['label_smoothing']

        # test time config
        self.test_pre_nms_thresh = test_cfg['pre_nms_thresh']
        self.test_pre_nms_topk = test_cfg['pre_nms_topk']
        self.test_iou_threshold = test_cfg['iou_threshold']
        self.test_min_score = test_cfg['min_score']
        self.test_max_seg_num = test_cfg['max_seg_num']
        self.test_nms_method = test_cfg['nms_method']
        assert self.test_nms_method in ['soft', 'hard', 'none']
        self.test_duration_thresh = test_cfg['duration_thresh']
        self.test_multiclass_nms = test_cfg['multiclass_nms']
        self.test_nms_sigma = test_cfg['nms_sigma']
        self.test_voting_thresh = test_cfg['voting_thresh']

        # we will need a better way to dispatch the params to backbones / necks
        # backbone network: conv + transformer
        assert backbone_type in ['convTransformer', 'conv']
        if backbone_type == 'convTransformer':
            self.backbone_visual = make_backbone(
                'convTransformer',
                **{
                    'n_in' : input_dim,
                    'n_embd' : embd_dim,
                    'n_head': n_head,
                    'n_embd_ks': embd_kernel_size,
                    'max_len': max_seq_len,
                    'arch' : backbone_arch,
                    'mha_win_size': self.mha_win_size,
                    'scale_factor' : scale_factor,
                    'with_ln' : embd_with_ln,
                    'attn_pdrop' : 0.0,
                    'proj_pdrop' : self.train_dropout,
                    'path_pdrop' : self.train_droppath,
                    'use_abs_pe' : use_abs_pe,
                    'use_rel_pe' : use_rel_pe
                }
            )

            self.backbone_audio = make_backbone(
                'convTransformer',
                **{
                    'n_in' : input_dim,
                    'n_embd' : embd_dim,
                    'n_head': n_head,
                    'n_embd_ks': embd_kernel_size,
                    'max_len': max_seq_len,
                    'arch' : backbone_arch,
                    'mha_win_size': self.mha_win_size,
                    'scale_factor' : scale_factor,
                    'with_ln' : embd_with_ln,
                    'attn_pdrop' : 0.0,
                    'proj_pdrop' : self.train_dropout,
                    'path_pdrop' : self.train_droppath,
                    'use_abs_pe' : use_abs_pe,
                    'use_rel_pe' : use_rel_pe
                }
            )
        else:
            self.backbone = make_backbone(
                'conv',
                **{
                    'n_in': input_dim,
                    'n_embd': embd_dim,
                    'n_embd_ks': embd_kernel_size,
                    'arch': backbone_arch,
                    'scale_factor': scale_factor,
                    'with_ln' : embd_with_ln
                }
            )

        # fpn network: convs
        assert fpn_type in ['fpn', 'identity']
        self.neck_visual = make_neck(
            fpn_type,
            **{
                'in_channels' : [embd_dim] * (backbone_arch[-1] + 1),
                'out_channel' : fpn_dim,
                'scale_factor' : scale_factor,
                'with_ln' : fpn_with_ln
            }
        )

        self.neck_audio = make_neck(
            fpn_type,
            **{
                'in_channels' : [embd_dim] * (backbone_arch[-1] + 1),
                'out_channel' : fpn_dim,
                'scale_factor' : scale_factor,
                'with_ln' : fpn_with_ln
            }
        )

        # location generator: points
        self.point_generator = make_generator(
            'point',
            **{
                'max_seq_len' : max_seq_len * max_buffer_len_factor,
                'fpn_levels' : len(self.fpn_strides),
                'scale_factor' : scale_factor,
                'regression_range' : self.reg_range
            }
        )


        self.cls_head_verb = PtTransformerClsHeadV(
            fpn_dim, head_dim, self.num_classes_verb,
            kernel_size=head_kernel_size,
            prior_prob=self.train_cls_prior_prob,
            with_ln=head_with_ln,
            empty_cls=train_cfg['head_empty_cls_v']
        )

        self.cls_head_noun = PtTransformerClsHeadN(
            fpn_dim, head_dim, self.num_classes_noun,
            kernel_size=head_kernel_size,
            prior_prob=self.train_cls_prior_prob,
            with_ln=head_with_ln,
            empty_cls=train_cfg['head_empty_cls_n']
        )

        self.reg_head = PtTransformerRegHead(
            fpn_dim, head_dim, len(self.fpn_strides),
            kernel_size=head_kernel_size,
            with_ln=head_with_ln
        )



        ########################################################### audio ########################
        self.cls_head_verb_audio = PtTransformerClsHeadV(
            fpn_dim, head_dim, self.num_classes_verb,
            kernel_size=head_kernel_size,
            prior_prob=self.train_cls_prior_prob,
            with_ln=head_with_ln,
            empty_cls=train_cfg['head_empty_cls_v']
        )

        self.cls_head_noun_audio = PtTransformerClsHeadN(
            fpn_dim, head_dim, self.num_classes_noun,
            kernel_size=head_kernel_size,
            prior_prob=self.train_cls_prior_prob,
            with_ln=head_with_ln,
            empty_cls=train_cfg['head_empty_cls_n']
        )

        self.reg_head_audio = PtTransformerRegHead(
            fpn_dim, head_dim, len(self.fpn_strides),
            kernel_size=head_kernel_size,
            with_ln=head_with_ln
        )

        self.actionness_head_audio = AudioActionnessHead(
            512, head_dim, len(self.fpn_strides),
            kernel_size=head_kernel_size,
            with_ln=head_with_ln
        )
        # maintain an EMA of #foreground to stabilize the loss normalizer
        # useful for small mini-batch training
        self.loss_normalizer = train_cfg['init_loss_norm']
        self.loss_normalizer_momentum = 0.9

        self.cross_attn = CrossAttention(
            query_dim=fpn_dim,
            cross_attention_dim=fpn_dim,
            heads=8,
            dim_head=head_dim,
            dropout=0.5,
            bias=False,
            upcast_attention=False,
            upcast_softmax=False,
            added_kv_proj_dim=None,
            norm_num_groups=None,
            processor=None
        )



    @property
    def device(self):
        # a hacky way to get the device type
        # will throw an error if parameters are on different devices
        return list(set(p.device for p in self.parameters()))[0]

    def forward(self, video_list, args, cross_attention_kwargs=None):
        # batch the video list into feats (B, C, T) and masks (B, 1, T)
        batched_inputs_visual, batched_masks_visual = self.preprocessing_visual(video_list)
        batched_inputs_audio, batched_masks_audio = self.preprocessing_audio(video_list)

        if self.training:
            vid_idx = []
            vid_idx.append(video_list[0]['video_id'])
            vid_idx.append(video_list[1]['video_id'])

        # forward the network (backbone -> neck -> heads)
        feats_visual, masks_visual = self.backbone_visual(batched_inputs_visual, batched_masks_visual)
        fpn_feats_visual, fpn_masks_visual = self.neck_visual(feats_visual, masks_visual)

        #feats_audio, masks_audio = self.backbone_visual(batched_inputs_audio, batched_masks_audio)
        feats_audio, masks_audio = self.backbone_audio(batched_inputs_audio, batched_masks_audio)
        fpn_feats_audio, fpn_masks_audio = self.neck_audio(feats_audio, masks_audio)

        visual_audio_fusion_feat = []
        for level, level_feat in enumerate(fpn_feats_visual):
            
            visual_audio = []

            level_feat = torch.transpose(level_feat,1,2)
            fpn_feats_audio_lel = torch.transpose(fpn_feats_audio[level],1,2)
            cross_attention_kwargs = cross_attention_kwargs if cross_attention_kwargs is not None else {}
            attn_output = self.cross_attn(
                    level_feat,
                    encoder_hidden_states=fpn_feats_audio_lel,
                    attention_mask=None,
                    **cross_attention_kwargs,
                )

            out = torch.transpose(attn_output,1,2)

            visual_audio_fusion_feat.append(out)

        points = self.point_generator(fpn_feats_visual)


        ################################# visual ####################################3
        out_cls_logits_verb_visual = self.cls_head_verb(fpn_feats_visual, fpn_masks_visual)
        out_cls_logits_noun_visual = self.cls_head_noun(fpn_feats_visual, fpn_masks_visual)
        out_offsets_visual, out_conf_visual = self.reg_head(fpn_feats_visual, fpn_masks_visual)

        out_cls_logits_verb_visual = [x.permute(0, 2, 1) for x in out_cls_logits_verb_visual]
        out_cls_logits_noun_visual = [x.permute(0, 2, 1) for x in out_cls_logits_noun_visual]

        out_offsets_visual = [x.permute(0, 2, 1) for x in out_offsets_visual]

        out_conf_visual = [x.permute(0, 2, 1) for x in out_conf_visual]

        fpn_masks_visual = [x.squeeze(1) for x in fpn_masks_visual]

        ################################# audio ####################################3
        out_cls_logits_verb_audio = self.cls_head_verb_audio (fpn_feats_audio, fpn_masks_audio)
        out_cls_logits_noun_audio  = self.cls_head_noun_audio (fpn_feats_audio, fpn_masks_audio)
        #out_offsets_audio , out_conf_audio  = self.reg_head_audio (fpn_feats_audio, fpn_masks_audio)

        ################################ audio + visual #################################
        out_cls_logits_actionness  = self.actionness_head_audio(visual_audio_fusion_feat, fpn_masks_audio)



        ######################################################################
        out_cls_logits_actionness= [x.permute(0, 2, 1) for x in out_cls_logits_actionness]
        out_cls_logits_verb_audio  = [x.permute(0, 2, 1) for x in out_cls_logits_verb_audio]
        out_cls_logits_noun_audio  = [x.permute(0, 2, 1) for x in out_cls_logits_noun_audio]
        # out_offsets_audio = [x.permute(0, 2, 1) for x in out_offsets_audio]
        # out_conf_audio = [x.permute(0, 2, 1) for x in out_conf_audio]
        fpn_masks_audio = [x.squeeze(1) for x in fpn_masks_audio]


        # return loss during training
        if self.training:
            # generate segment/lable List[N x 2] / List[N] with length = B
            assert video_list[0]['segments'] is not None, "GT action labels does not exist"
            assert video_list[0]['labels_v'] is not None, "GT action labels does not exist"
            assert video_list[0]['labels_n'] is not None, "GT action labels does not exist"
            gt_segments = [x['segments'].to(self.device) for x in video_list]
            gt_labels_v = [x['labels_v'].to(self.device) for x in video_list]
            gt_labels_n = [x['labels_n'].to(self.device) for x in video_list]

            gt_cls_labels_v, gt_cls_labels_n, gt_offsets, gt_start, gt_end, gt_action = self.label_points(args,
                points, gt_segments, gt_labels_v, gt_labels_n)


            losses_visaul = self.losses(
                args,
                vid_idx, 
                fpn_masks_visual,
                out_cls_logits_verb_visual, out_cls_logits_noun_visual, out_offsets_visual, out_conf_visual,
                gt_cls_labels_v, gt_cls_labels_n, gt_offsets, gt_start, gt_end, gt_action, out_cls_logits_actionness, is_audio = False
            )

            losses_audio = self.losses(
                args,
                vid_idx, 
                fpn_masks_audio,
                out_cls_logits_verb_audio, out_cls_logits_noun_audio, None, None,
                gt_cls_labels_v, gt_cls_labels_n, gt_offsets, gt_start, gt_end, gt_action, None, is_audio = True
            )

            losses = {}
            losses['cls_v'] = losses_visaul['cls_loss_v'] + args.loss_a_weight*losses_audio['cls_loss_v']
            losses['cls_n'] = losses_visaul['cls_loss_n'] + args.loss_a_weight*losses_audio['cls_loss_n']
            losses['reg_visual'] = losses_visaul['reg_loss']
            losses['action'] = losses_visaul['act_loss']

            losses['final_loss'] = losses['cls_v'] + losses['cls_n'] + losses['reg_visual'] + args.loss_act_weight*losses['action']

            return losses

        else:
            # decode the actions (sigmoid / stride, etc)
            results = self.inference(
                args,
                video_list, points, 
                fpn_masks_visual, out_cls_logits_verb_visual, out_cls_logits_noun_visual, out_offsets_visual, out_conf_visual, 
                fpn_masks_audio, out_cls_logits_verb_audio, out_cls_logits_noun_audio, out_cls_logits_actionness
            )
            return results

    @torch.no_grad()
    def preprocessing_visual(self, video_list, padding_val=0.0):
        """
            Generate batched features and masks from a list of dict items
        """
        feats = [x['feats_v'] for x in video_list]
        feats_lens = torch.as_tensor([feat.shape[-1] for feat in feats])
        max_len = feats_lens.max(0).values.item()

        if self.training:
            assert max_len <= self.max_seq_len, "Input length must be smaller than max_seq_len during training"
            # set max_len to self.max_seq_len
            max_len = self.max_seq_len
            # batch input shape B, C, T
            batch_shape = [len(feats), feats[0].shape[0], max_len]
            batched_inputs = feats[0].new_full(batch_shape, padding_val)
            for feat, pad_feat in zip(feats, batched_inputs):
                pad_feat[..., :feat.shape[-1]].copy_(feat)
        else:
            assert len(video_list) == 1, "Only support batch_size = 1 during inference"
            # input length < self.max_seq_len, pad to max_seq_len
            if max_len <= self.max_seq_len:
                max_len = self.max_seq_len
            else:
                # pad the input to the next divisible size
                stride = self.max_div_factor
                max_len = (max_len + (stride - 1)) // stride * stride
            padding_size = [0, max_len - feats_lens[0]]
            batched_inputs = F.pad(
                feats[0], padding_size, value=padding_val).unsqueeze(0)

        # generate the mask
        batched_masks = torch.arange(max_len)[None, :] < feats_lens[:, None]

        # push to device
        batched_inputs = batched_inputs.to(self.device)
        batched_masks = batched_masks.unsqueeze(1).to(self.device)

        return batched_inputs, batched_masks

    @torch.no_grad()
    def preprocessing_audio(self, video_list, padding_val=0.0):
        """
            Generate batched features and masks from a list of dict items
        """
        feats = [x['feats_a'] for x in video_list]
        feats_lens = torch.as_tensor([feat.shape[-1] for feat in feats])
        max_len = feats_lens.max(0).values.item()

        if self.training:
            assert max_len <= self.max_seq_len, "Input length must be smaller than max_seq_len during training"
            # set max_len to self.max_seq_len
            max_len = self.max_seq_len
            # batch input shape B, C, T
            batch_shape = [len(feats), feats[0].shape[0], max_len]
            batched_inputs = feats[0].new_full(batch_shape, padding_val)
            for feat, pad_feat in zip(feats, batched_inputs):
                pad_feat[..., :feat.shape[-1]].copy_(feat)
        else:
            assert len(video_list) == 1, "Only support batch_size = 1 during inference"
            # input length < self.max_seq_len, pad to max_seq_len
            if max_len <= self.max_seq_len:
                max_len = self.max_seq_len
            else:
                # pad the input to the next divisible size
                stride = self.max_div_factor
                max_len = (max_len + (stride - 1)) // stride * stride
            padding_size = [0, max_len - feats_lens[0]]
            batched_inputs = F.pad(
                feats[0], padding_size, value=padding_val).unsqueeze(0)

        # generate the mask
        batched_masks = torch.arange(max_len)[None, :] < feats_lens[:, None]

        # push to device
        batched_inputs = batched_inputs.to(self.device)
        batched_masks = batched_masks.unsqueeze(1).to(self.device)

        return batched_inputs, batched_masks


    def ioa_with_anchors(self,anchors_min,anchors_max,box_min,box_max):
        """Compute intersection between score a box and the anchors.
        """
        len_anchors=anchors_max-anchors_min
        int_xmin = np.maximum(anchors_min, box_min)
        int_xmax = np.minimum(anchors_max, box_max)
        inter_len = np.maximum(int_xmax - int_xmin, 0.)
        scores = np.divide(inter_len, len_anchors)
        return scores

    def iou_with_anchors(self,anchors_min, anchors_max, box_min, box_max):
        int_xmin = np.maximum(anchors_min, box_min)
        int_xmax = np.minimum(anchors_max, box_max)
        inter_len = np.maximum(int_xmax - int_xmin, 0.)
        union_len = (anchors_max - anchors_min) + (box_max - box_min) - inter_len
        iou = np.divide(inter_len, union_len)
        return iou

    @torch.no_grad()
    def label_points(self, args, points, gt_segments, gt_labels_v, gt_labels_n):
        # concat points on all fpn levels List[T x 4] -> F T x 4
        # This is shared for all samples in the mini-batch
        num_levels = len(points)
        concat_points = torch.cat(points, dim=0)
        gt_cls_v, gt_cls_n, gt_offset, gt_start, gt_end, gt_action = [], [], [], [], [], []

        # loop over each video sample
        for gt_segment, gt_label_v, gt_label_n in zip(gt_segments, gt_labels_v, gt_labels_n):
            cls_targets_v, cls_targets_n, reg_targets, starting_gt, ending_gt, action_gt = self.label_points_single_video(args,
                concat_points, gt_segment, gt_label_v, gt_label_n
            )
            # append to list (len = # images, each of size FT x C)
            gt_cls_v.append(cls_targets_v)
            gt_cls_n.append(cls_targets_n)
            gt_offset.append(reg_targets)
            gt_start.append(starting_gt)
            gt_end.append(ending_gt)
            gt_action.append(action_gt)

        return gt_cls_v, gt_cls_n, gt_offset, gt_start, gt_end, gt_action

    @torch.no_grad()
    def label_points_single_video(self, args, concat_points, gt_segment, gt_label_v, gt_label_n):
        # concat_points : F T x 4 (t, regressoin range, stride)
        # gt_segment : N (#Events) x 2
        # gt_label : N (#Events) x 1
        num_pts = concat_points.shape[0]
        num_gts = gt_segment.shape[0]

        # corner case where current sample does not have actions
        if num_gts == 0:
            cls_targets_v = gt_label_v.new_full((num_pts,), self.num_classes_verb)
            cls_targets_n = gt_label_n.new_full((num_pts,), self.num_classes_noun)
            reg_targets = gt_segment.new_zeros((num_pts, 2))
            return cls_targets_v, cls_targets_n, reg_targets

        # compute the lengths of all segments -> F T x N
        lens = gt_segment[:, 1] - gt_segment[:, 0]
        lens = lens[None, :].repeat(num_pts, 1)

        # compute the distance of every point to each segment boundary
        # auto broadcasting for all reg target-> F T x N x2
        gt_segs = gt_segment[None].expand(num_pts, num_gts, 2)   # shape = (4536, num of gt_segments ,2)
        left = concat_points[:, 0, None] - gt_segs[:, :, 0]
        right = gt_segs[:, :, 1] - concat_points[:, 0, None]
        reg_targets = torch.stack((left, right), dim=-1) #shape = (4536, diff_num_segs, 2)


        if self.train_center_sample == 'radius':
            # center of all segments F T x N
            center_pts = 0.5 * (gt_segs[:, :, 0] + gt_segs[:, :, 1])
            # center sampling based on stride radius
            # compute the new boundaries:
            # concat_points[:, 3] stores the stride
            t_mins = \
                center_pts - concat_points[:, 3, None] * self.train_center_sample_radius
            t_maxs = \
                center_pts + concat_points[:, 3, None] * self.train_center_sample_radius
            # prevent t_mins / maxs from over-running the action boundary
            # left: torch.maximum(t_mins, gt_segs[:, :, 0])
            # right: torch.minimum(t_maxs, gt_segs[:, :, 1])
            # F T x N (distance to the new boundary)
            cb_dist_left = concat_points[:, 0, None] \
                           - torch.maximum(t_mins, gt_segs[:, :, 0])
            cb_dist_right = torch.minimum(t_maxs, gt_segs[:, :, 1]) \
                            - concat_points[:, 0, None]
            # F T x N x 2
            center_seg = torch.stack(
                (cb_dist_left, cb_dist_right), -1)
            # F T x N
            inside_gt_seg_mask = center_seg.min(-1)[0] > 0
        else:
            # inside an gt action
            inside_gt_seg_mask = reg_targets.min(-1)[0] > 0

        # limit the regression range for each location
        max_regress_distance = reg_targets.max(-1)[0]
        # F T x N
        inside_regress_range = (
            (max_regress_distance >= concat_points[:, 1, None])
            & (max_regress_distance <= concat_points[:, 2, None])
        )

        # if there are still more than one actions for one moment
        # pick the one with the shortest duration (easiest to regress)
        lens.masked_fill_(inside_gt_seg_mask==0, float('inf'))
        lens.masked_fill_(inside_regress_range==0, float('inf'))
        # F T
        min_len, min_len_inds = lens.min(dim=1)

        cls_targets_v = gt_label_v[min_len_inds] 
        cls_targets_n = gt_label_n[min_len_inds]

        # set unmatched points as BG
        cls_targets_v.masked_fill_(min_len==float('inf'), float(self.num_classes_verb))
        cls_targets_n.masked_fill_(min_len==float('inf'), float(self.num_classes_noun))

        reg_targets = reg_targets[range(num_pts), min_len_inds]
        # reg_targets.shape_before = (4536, N(event), 2), choose a best gt_seg for each point

        # normalization based on stride
        reg_targets /= concat_points[:, 3, None]


        ##################################### boundary lable ##########################################
        action_gt = []
        starting_gt = []
        ending_gt = []

        gt_bbox=gt_segment.cpu().numpy()
        #break
        num_levels = [2304, 1152, 576, 288, 144, 72]
        level_ratio = [1, 2, 4, 8, 16, 32] 
        for level in range(6):

            gt_xmins=gt_bbox[:,0]/level_ratio[level]
            gt_xmaxs=gt_bbox[:,1]/level_ratio[level]

            anchor_xmin=[x for x in range(num_levels[level])]
            anchor_xmax=[x+1 for x in range(num_levels[level])]
            
            gt_lens=gt_xmaxs-gt_xmins
            gt_len_small=np.maximum(1,0.1*gt_lens)

            anchor_xmin_cen=anchor_xmin.copy()
            anchor_xmax_cen=anchor_xmax.copy()

            for i,x in enumerate(range(num_levels[level])):
                for gt_i in range(len(gt_xmins)):
                    if x in range(int(gt_xmins[gt_i]),int(gt_xmaxs[gt_i]),1):
                        cen_gap = np.maximum(1, gt_xmaxs[gt_i] - gt_xmins[gt_i])
                        anchor_xmin_cen[i] = np.maximum(1, x - cen_gap/2)
                        anchor_xmax_cen[i] = x + cen_gap/2


            gt_start_bboxs=np.stack((gt_xmins-gt_len_small/2,gt_xmins+gt_len_small/2),axis=1)
            gt_end_bboxs=np.stack((gt_xmaxs-gt_len_small/2,gt_xmaxs+gt_len_small/2),axis=1)

            ##################################### Gaussian centerness label ############################################
            gt_center = (gt_xmins+gt_xmaxs)/2

            match_score_action=[0.1]*len(anchor_xmin)            
            for ii in range(len(anchor_xmin)):
                for gt_id in range(len(gt_xmins)):
                    if ii >= gt_xmins[gt_id] and ii <= gt_xmaxs[gt_id]:
                        distance_cen =  torch.Tensor([abs(ii - gt_center[gt_id])])
                        centerness_value = torch.exp(torch.div(-torch.square(distance_cen),2*args.cen_gau_sigma*args.cen_gau_sigma))
                        match_score_action[ii] = centerness_value
            ###################################################################################################

            match_score_start=[]
            for jdx in range(len(anchor_xmin)):
                match_score_start.append(np.max(self.ioa_with_anchors(anchor_xmin[jdx],anchor_xmax[jdx],gt_start_bboxs[:,0],gt_start_bboxs[:,1])))
            match_score_end=[]
            for jdx in range(len(anchor_xmin)):
                match_score_end.append(np.max(self.ioa_with_anchors(anchor_xmin[jdx],anchor_xmax[jdx],gt_end_bboxs[:,0],gt_end_bboxs[:,1])))

            action_gt = action_gt + match_score_action
            starting_gt = starting_gt + match_score_start
            ending_gt = ending_gt  + match_score_end


        action_gt = torch.Tensor(action_gt)
        starting_gt = torch.Tensor(starting_gt)
        ending_gt = torch.Tensor(ending_gt)

        return cls_targets_v, cls_targets_n, reg_targets, starting_gt, ending_gt, action_gt

    def losses(
        self, args, vid_idx, fpn_masks,
        out_cls_logits_v, out_cls_logits_n, out_offsets, out_conf,
        gt_cls_labels_v, gt_cls_labels_n, gt_offsets, gt_start, gt_end, gt_action, out_actionness_audio, is_audio = True
    ):
        # fpn_masks, out_*: F (List) [B, T_i, C]
        # gt_* : B (list) [F T, C]
        # fpn_masks -> (B, FT)
        valid_mask = torch.cat(fpn_masks, dim=1)

        # 1. classification loss
        # stack the list -> (B, FT) -> (# Valid, )
        gt_cls_v = torch.stack(gt_cls_labels_v)
        gt_cls_n = torch.stack(gt_cls_labels_n)
        pos_mask = (gt_cls_n >= 0) & (gt_cls_n != self.num_classes_noun) &(gt_cls_v >= 0) & (gt_cls_v != self.num_classes_verb) & valid_mask

        # shape of out_offsets = (6, 2, T (2304, 1152, ..., 72),2)
        # shape of out_conf = (6, 2, T (2304, 1152, ..., 72),1)


        # cat the predicted offsets -> (B, FT, 2 (xC)) -> # (#Pos, 2 (xC))

        if is_audio == False:
            pred_offsets = torch.cat(out_offsets, dim=1)[pos_mask]
            pred_conf = torch.cat(out_conf, dim=1)[pos_mask]
            out_actionness_audio = torch.cat(out_actionness_audio, dim=1)[pos_mask]
        #out_actionness_audio = out_actionness_audio.squeeze()
        # shape of pred_offsets = (6, 2, T (2304, 1152, ..., 72),2) ---> (2, 4536, 2)
        # shape of pred_offsets = (6, 2, T (2304, 1152, ..., 72),1) ---> (2, 4536, 2)


        gt_offsets = torch.stack(gt_offsets)[pos_mask]
        gt_start = torch.stack(gt_start)[pos_mask]
        gt_end = torch.stack(gt_end)[pos_mask]
        gt_action = torch.stack(gt_action)[pos_mask]

        # update the loss normalizer
        num_pos = pos_mask.sum().item()
        self.loss_normalizer = self.loss_normalizer_momentum * self.loss_normalizer + (
            1 - self.loss_normalizer_momentum
        ) * max(num_pos, 1)

        ############################## verb ##############################
        # #cls + 1 (background)
        gt_target_v = F.one_hot(
            gt_cls_v[valid_mask], num_classes=self.num_classes_verb + 1
        )[:, :-1]
        gt_target_v = gt_target_v.to(out_cls_logits_v[0].dtype)

        # optinal label smoothing
        gt_target_v *= 1 - self.train_label_smoothing
        gt_target_v += self.train_label_smoothing / (self.num_classes_verb + 1)

        # focal loss
        cls_loss_v = sigmoid_focal_loss(
            torch.cat(out_cls_logits_v, dim=1)[valid_mask],
            gt_target_v,
            reduction='sum'
        )
        cls_loss_v /= 250#self.loss_normalizer

        ############################## noun ##############################
        # #cls + 1 (background)
        gt_target_n = F.one_hot(
            gt_cls_n[valid_mask], num_classes=self.num_classes_noun + 1
        )[:, :-1]
        gt_target_n = gt_target_n.to(out_cls_logits_n[0].dtype)

        # optinal label smoothing
        gt_target_n *= 1 - self.train_label_smoothing
        gt_target_n += self.train_label_smoothing / (self.num_classes_noun + 1)

        # focal loss
        cls_loss_n = sigmoid_focal_loss(
            torch.cat(out_cls_logits_n, dim=1)[valid_mask],
            gt_target_n,
            reduction='sum'
        )
        cls_loss_n /= 500#self.loss_normalizer


        cls_loss_v = args.verb_cls_weight * cls_loss_v
        cls_loss_n = args.noun_cls_weight * cls_loss_n 



        ####################### actionness loss for audio ########################
        # if is_audio == True:
        #     act_loss = binary_logistic_loss(gt_action,out_actionness_audio)

        # 2. regression using IoU/GIoU loss (defined on positive samples)
        if is_audio == False:

            if num_pos == 0:
                reg_loss = 0 * pred_offsets.sum() 
            else:
                # giou loss defined on positive samples

                reg_loss, actionness_loss = ctr_giou_loss_1d(args,
                    vid_idx,
                    pred_offsets, pred_conf, out_actionness_audio,
                    gt_offsets, gt_start, gt_end, gt_action,
                    reduction='sum'
                )
                reg_loss /= self.loss_normalizer

            return {'cls_loss_v'   : cls_loss_v,
                    'cls_loss_n'   : cls_loss_n,
                    'reg_loss'   : reg_loss,
                    'act_loss' : actionness_loss}

        elif is_audio == True:
            return {'cls_loss_v'   : cls_loss_v,
                    'cls_loss_n'   : cls_loss_n}

    @torch.no_grad()
    def inference(
        self,
        args,
        video_list,
        points,
        fpn_masks_visual, out_cls_logits_verb_visual, out_cls_logits_noun_visual, out_offsets_visual, out_conf_visual, 
        fpn_masks_audio, out_cls_logits_verb_audio, out_cls_logits_noun_audio, out_cls_logits_actionness_audio
    ):
        # video_list B (list) [dict]
        # points F (list) [T_i, 4]
        # fpn_masks, out_*: F (List) [B, T_i, C]
        results = []

        # 1: gather video meta information
        vid_idxs = [x['video_id'] for x in video_list]
        vid_fps = [x['fps'] for x in video_list]
        vid_lens = [x['duration'] for x in video_list]
        vid_ft_stride = [x['feat_stride'] for x in video_list]
        vid_ft_nframes = [x['feat_num_frames'] for x in video_list]

        # 2: inference on each single video and gather the results
        # upto this point, all results use timestamps defined on feature grids
        for idx, (vidx, fps, vlen, stride, nframes) in enumerate(
            zip(vid_idxs, vid_fps, vid_lens, vid_ft_stride, vid_ft_nframes)
        ):
            ################################# visual #######################################
            cls_logits_per_vid_verb_visual = [x[idx] for x in out_cls_logits_verb_visual]
            cls_logits_per_vid_noun_visual = [x[idx] for x in out_cls_logits_noun_visual]
            offsets_per_vid_visual = [x[idx] for x in out_offsets_visual]
            conf_per_vid_visual = [x[idx] for x in out_conf_visual]
            fpn_masks_per_vid_visual = [x[idx] for x in fpn_masks_visual]


            ################################# audio #######################################
            cls_logits_per_vid_verb_audio = [x[idx] for x in out_cls_logits_verb_audio]
            cls_logits_per_vid_noun_audio = [x[idx] for x in out_cls_logits_noun_audio]
            actionness = [x[idx] for x in out_cls_logits_actionness_audio]

            
            # offsets_per_vid_audio = [x[idx] for x in out_offsets_audio]
            # conf_per_vid_audio = [x[idx] for x in out_conf_audio]
            fpn_masks_per_vid_audio = [x[idx] for x in fpn_masks_audio]
            # inference on a single video (should always be the case)

            results_per_vid = self.inference_single_video(args, points, vidx,
                fpn_masks_per_vid_visual, cls_logits_per_vid_verb_visual, cls_logits_per_vid_noun_visual, offsets_per_vid_visual, conf_per_vid_visual,
                fpn_masks_per_vid_audio, cls_logits_per_vid_verb_audio, cls_logits_per_vid_noun_audio, actionness)

                
            # pass through video meta info
            results_per_vid['video_id'] = vidx
            results_per_vid['fps'] = fps
            results_per_vid['duration'] = vlen
            results_per_vid['feat_stride'] = stride
            results_per_vid['feat_num_frames'] = nframes
            results.append(results_per_vid)



        # step 3: postprocssing
        results = self.postprocessing(results)




        return results

    @torch.no_grad()
    def inference_single_video(
        self, args, points, vidx,
        fpn_masks_visual, out_cls_logits_verb_visual, out_cls_logits_noun_visual, out_offsets_visual, out_conf_visual,
        fpn_masks_audio, out_cls_logits_verb_audio, out_cls_logits_noun_audio, out_actionness
    ):
        # points F (list) [T_i, 4]
        # fpn_masks, out_*: F (List) [T_i, C]
        segs_all = []
        scores_all = []
        scores_cls = []
        scores_start = []
        scores_end = []       
        cls_idxs_verb_all = []
        cls_idxs_noun_all = []
        level=0
        # loop over fpn levels
        for pts_i, mask_i, cls_i_verb_visual, cls_i_noun_visual, offsets_i, out_conf_i, mask_i_audio, cls_i_verb_audio, cls_i_noun_audio, actionness_i in zip(
            points, fpn_masks_visual, out_cls_logits_verb_visual, out_cls_logits_noun_visual, out_offsets_visual, out_conf_visual, fpn_masks_audio, out_cls_logits_verb_audio, out_cls_logits_noun_audio, out_actionness):
            level = level+1

            input_conf_s = torch.exp(torch.div(-torch.square(out_conf_i[:, 0]),2*args.gau_sigma*args.gau_sigma))
            input_conf_e = torch.exp(torch.div(-torch.square(out_conf_i[:, 1]),2*args.gau_sigma*args.gau_sigma))
 
            conf_s = input_conf_s.sigmoid().cpu()
            conf_e = input_conf_e.sigmoid().cpu()

            gt_val_s_i_new = [conf_s[min(len(conf_s)-1,max(0,int(x - offsets_i[x][0])))] for x in range(len(conf_s))]
            gt_val_s_i = torch.Tensor(gt_val_s_i_new)#.sigmoid()
            gt_val_e_i_new = [conf_e[min(len(conf_e)-1,max(0,int(x + offsets_i[x][1])))] for x in range(len(conf_e))]
            gt_val_e_i = torch.Tensor(gt_val_e_i_new)#.sigmoid()

            if len(gt_val_s_i) < len(pts_i):
                gt_val_s_i = torch.cat((gt_val_s_i,torch.zeros(len(pts_i)-len(gt_val_s_i))),0)
            if len(gt_val_e_i) < len(pts_i):
                gt_val_e_i = torch.cat((gt_val_e_i,torch.zeros(len(pts_i)-len(gt_val_e_i))),0)


            cls_i_verb = cls_i_verb_visual + 0.2*cls_i_verb_audio + args.actionness_ratio * actionness_i.repeat(1,97) + 0.3*(gt_val_s_i+gt_val_e_i).cuda().unsqueeze(1).repeat(1,97)
            cls_i_noun = cls_i_noun_visual + 0.2*cls_i_noun_audio + args.actionness_ratio * actionness_i.repeat(1,300) + 0.3*(gt_val_s_i+gt_val_e_i).cuda().unsqueeze(1).repeat(1,300)

            cls_verb_score, cls_verb_label = torch.sort(cls_i_verb.sigmoid(),descending=True,dim=1)  #torch.max(cls_i_verb.sigmoid(), 1)
            cls_noun_score, cls_noun_label = torch.sort(cls_i_noun.sigmoid(),descending=True,dim=1) #torch.max(cls_i_noun.sigmoid(), 1)

            verb_topk, noun_topk = 11, 33
            cls_verb_score_topk = cls_verb_score[:,:verb_topk]* mask_i.unsqueeze(-1)
            cls_verb_label_topk = cls_verb_label[:,:verb_topk]* mask_i.unsqueeze(-1)

            cls_noun_score_topk = cls_noun_score[:,:noun_topk]* mask_i.unsqueeze(-1)
            cls_noun_label_topk = cls_noun_label[:,:noun_topk]* mask_i.unsqueeze(-1)

            action_label_all = []

            mul_cls_score = torch.mul(cls_noun_score_topk.unsqueeze(dim=-1),cls_verb_score_topk.unsqueeze(dim=1))# * mask_i.unsqueeze(-1).unsqueeze(-1)
            pred_prob = mul_cls_score.flatten() #cls_noun_score*cls_verb_score#*cls_noun_score#cls_verb_score * cls_noun_score


            # Apply filtering to make NMS faster following detectron2
            # 1. Keep seg with confidence score > a threshold
            keep_idxs1 = (pred_prob > self.test_pre_nms_thresh * self.test_pre_nms_thresh)
            pred_prob = pred_prob[keep_idxs1]
            topk_idxs = keep_idxs1.nonzero(as_tuple=True)[0]

            # 2. Keep top k top scoring boxes only
            num_topk = min(self.test_pre_nms_topk, topk_idxs.size(0))
            pred_prob, idxs = pred_prob.sort(descending=True)
            pred_prob = pred_prob[:num_topk].clone()
            topk_idxs = topk_idxs[idxs[:num_topk]].clone()


            # fix a warning in pytorch 1.9

            ########################### for multiply verb and noun scores #########################

            pt_idxs =  torch.div(
                topk_idxs, verb_topk*noun_topk, rounding_mode='floor'
            )
            dx_loc = torch.fmod(topk_idxs, verb_topk*noun_topk)

            cls_noun_idxs1 = torch.div(dx_loc, verb_topk, rounding_mode='floor')
            cls_verb_idxs1 = torch.fmod(dx_loc, verb_topk)

            cls_noun_idxs = cls_noun_label_topk[pt_idxs,cls_noun_idxs1]
            cls_verb_idxs = cls_verb_label_topk[pt_idxs,cls_verb_idxs1]
            #####################################################################################3

            # 3. gather predicted offsets
            offsets = offsets_i[pt_idxs]
            pts = pts_i[pt_idxs]

            # 4. compute predicted segments (denorm by stride for output offsets)
            seg_left = pts[:, 0] - offsets[:, 0] * pts[:, 3]
            seg_right = pts[:, 0] + offsets[:, 1] * pts[:, 3]
            pred_segs = torch.stack((seg_left, seg_right), -1)

            # 5. Keep seg with duration > a threshold (relative to feature grids)
            seg_areas = seg_right - seg_left
            keep_idxs2 = seg_areas > self.test_duration_thresh

            segs_all.append(pred_segs[keep_idxs2])
            scores_all.append(pred_prob[keep_idxs2])

            cls_idxs_verb_all.append(cls_verb_idxs[keep_idxs2])
            cls_idxs_noun_all.append(cls_noun_idxs[keep_idxs2])

        # cat along the FPN levels (F N_i, C)

        segs_all, scores_all, cls_idxs_verb_all, cls_idxs_noun_all = [
            torch.cat(x) for x in [segs_all, scores_all, cls_idxs_verb_all, cls_idxs_noun_all]
        ]
        cls_idxs_action_all = []


        results = {'segments' : segs_all,
                   'scores'   : scores_all,
                   'labels_verb'   : cls_idxs_verb_all,
                   'labels_noun'   : cls_idxs_noun_all}


        return results



    @torch.no_grad()
    def postprocessing(self, results):
        # input : list of dictionary items
        # (1) push to CPU; (2) NMS; (3) convert to actual time stamps
        processed_results = []
        for results_per_vid in results:
            # unpack the meta info
            vidx = results_per_vid['video_id']
            fps = results_per_vid['fps']
            vlen = results_per_vid['duration']
            stride = results_per_vid['feat_stride']
            nframes = results_per_vid['feat_num_frames']
            # 1: unpack the results and move to CPU
            segs = results_per_vid['segments'].detach().cpu()
            scores = results_per_vid['scores'].detach().cpu()
            labels_verb = results_per_vid['labels_verb'].detach().cpu()
            labels_noun = results_per_vid['labels_noun'].detach().cpu()
            #labels_action = results_per_vid['labels_action']#.detach().cpu()
            if self.test_nms_method != 'none':
                # 2: batched nms (only implemented on CPU)

                segs, scores, labels_verb, labels_noun = batched_nms(
                    segs, scores, labels_verb, labels_noun,
                    self.test_iou_threshold,
                    self.test_min_score,
                    self.test_max_seg_num,
                    use_soft_nms = (self.test_nms_method == 'soft'),
                    multiclass = self.test_multiclass_nms,
                    sigma = self.test_nms_sigma,
                    voting_thresh = self.test_voting_thresh
                )
            # 3: convert from feature grids to seconds
            if segs.shape[0] > 0:

                segs = (segs * stride + 0.5 * nframes) / fps
                # truncate all boundaries within [0, duration]
                segs[segs<=0.0] *= 0.0
                segs[segs>=vlen] = segs[segs>=vlen] * 0.0 + vlen

            #4: repack the results
            processed_results.append(
                {'video_id' : vidx,
                 'segments' : segs,
                 'scores'   : scores,
                 'labels_verb'   : labels_verb,
                 'labels_noun'   : labels_noun}
            )

        return processed_results

