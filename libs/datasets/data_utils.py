import os
import copy
import random
import numpy as np
import random
import torch
from datetime import datetime

def trivial_batch_collator(batch):
    """
        A batch collator that does nothing
    """
    return batch

def worker_init_reset_seed(worker_id):
    """
        Reset random seed for each worker
    """
    seed = torch.initial_seed() % 2 ** 31
    np.random.seed(seed)
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)

def truncate_feats(
    data_dict,
    max_seq_len,
    trunc_thresh,
    seed,
    crop_ratio=None,
    max_num_trials=200,
    has_action=True,
    no_trunc=False
):
    """
    Truncate feats and time stamps in a dict item

    data_dict = {'video_id'        : str
                 'feats'           : Tensor C x T
                 'segments'        : Tensor N x 2 (in feature grid)
                 'labels'          : Tensor N
                 'fps'             : float
                 'feat_stride'     : int
                 'feat_num_frames' : in

    """
    # get the meta info
    feat_len = data_dict['feats_v'].shape[1]
    num_segs = data_dict['segments'].shape[0]

    # seq_len < max_seq_len
    if feat_len <= max_seq_len:
        # do nothing
        if crop_ratio == None:
            return data_dict
        # randomly crop the seq by setting max_seq_len to a value in [l, r]
        else:
            max_seq_len = random.randint(
                max(round(crop_ratio[0] * feat_len), 1),
                min(round(crop_ratio[1] * feat_len), feat_len),
            )
            # # corner case
            if feat_len == max_seq_len:
                return data_dict

    # otherwise, deep copy the dict
    data_dict = copy.deepcopy(data_dict)

    # try a few times till a valid truncation with at least one action
    #print('==================================================')
    #print(data_dict['video_id'])
    #print(max_num_trials)
    random_state = {}
    for _ in range(max_num_trials):

        # sample a random truncation of the video feats
        #random.seed(6155645791486980374)
        #if data_dict['video_id'] == 'P31_14':

        #print(data_dict['video_id'])
        # x=random.getstate()
        # np.save('./seed.npy', x)


        #x = np.load('./seed.npy', allow_pickle=True)
        #random.setstate(x)

        #random.seed(seed)
        #random.seed(1234567891)
        st = random.randint(0, feat_len - max_seq_len)
        
        #print(datetime.now())
        #print(st)
        ed = st + max_seq_len
        window = torch.as_tensor([st, ed], dtype=torch.float32)

        # compute the intersection between the sampled window and all segments
        window = window[None].repeat(num_segs, 1)
        left = torch.maximum(window[:, 0], data_dict['segments'][:, 0])
        right = torch.minimum(window[:, 1], data_dict['segments'][:, 1])
        inter = (right - left).clamp(min=0)
        area_segs = torch.abs(
            data_dict['segments'][:, 1] - data_dict['segments'][:, 0])
        inter_ratio = inter / area_segs

        # only select those segments over the thresh
        seg_idx = (inter_ratio >= trunc_thresh)

        if no_trunc:
            # with at least one action and not truncating any actions
            seg_trunc_idx = (inter_ratio > 0.0) & (inter_ratio < 1.0)
            if (seg_idx.sum().item() > 0) and (seg_trunc_idx.sum().item() == 0):
                break
        elif has_action:
            # with at least one action
            if seg_idx.sum().item() > 0:
                break
        else:
            # without any constraints
            break
    #print(random_state)
    # feats: C x T
    data_dict['feats_v'] = data_dict['feats_v'][:, st:ed].clone()
    data_dict['feats_a'] = data_dict['feats_a'][:, st:ed].clone()
    # segments: N x 2 in feature grids
    data_dict['segments'] = torch.stack((left[seg_idx], right[seg_idx]), dim=1)
    # shift the time stamps due to truncation
    data_dict['segments'] = data_dict['segments'] - st
    # labels: N
    data_dict['labels_v'] = data_dict['labels_v'][seg_idx].clone()
    data_dict['labels_n'] = data_dict['labels_n'][seg_idx].clone()
    return data_dict
