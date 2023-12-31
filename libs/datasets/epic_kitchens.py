import os
import json
import numpy as np

import torch
from torch.utils.data import Dataset
from torch.nn import functional as F

from .datasets import register_dataset
from .data_utils import truncate_feats

@register_dataset("epic")
class EpicKitchensDataset(Dataset):
    def __init__(
        self,
        is_training,     # if in training mode
        split,           # split, a tuple/list allowing concat of subsets
        seed,
        feat_folder_v,     # folder for features
        feat_folder_a,     # folder for features
        json_file,       # json file for annotations
        feat_stride,     # temporal stride of the feats
        num_frames,      # number of frames for each feat
        default_fps,     # default fps
        downsample_rate, # downsample rate for feats
        max_seq_len,     # maximum sequence length during training
        trunc_thresh,    # threshold for truncate an action segment
        crop_ratio,      # a tuple (e.g., (0.9, 1.0)) for random cropping
        input_dim,       # input feat dim
        num_classes_v,     # number of action categories
        num_classes_n,     # number of action categories
        file_prefix,     # feature file prefix if any
        file_ext_v,        # feature file extension if any
        file_ext_a,        # feature file extension if any
        force_upsampling # force to upsample to max_seq_len
    ):
        # file path
        assert os.path.exists(feat_folder_v) and os.path.exists(json_file)
        assert isinstance(split, tuple) or isinstance(split, list)
        assert crop_ratio == None or len(crop_ratio) == 2
        self.feat_folder_v = feat_folder_v
        self.feat_folder_a = feat_folder_a
        if file_prefix is not None:
            self.file_prefix = file_prefix
        else:
            self.file_prefix = ''
        self.file_ext_v = file_ext_v
        self.file_ext_a = file_ext_a
        self.json_file = json_file

        # split / training mode
        self.split = split
        self.is_training = is_training
        self.seed = seed

        #
        #self.modal = modal

        # features meta info
        self.feat_stride = feat_stride
        self.num_frames = num_frames
        self.input_dim = input_dim
        self.default_fps = default_fps
        self.downsample_rate = downsample_rate
        self.max_seq_len = max_seq_len
        self.trunc_thresh = trunc_thresh
        self.num_classes_v = num_classes_v
        self.num_classes_n = num_classes_n
        self.label_dict_v = None
        self.label_dict_n = None
        self.crop_ratio = crop_ratio

        # load database and select the subset
        dict_db, label_dict_v, label_dict_n = self._load_json_db(self.json_file)
        # "empty" noun categories on epic-kitchens
        # print(label_dict_v)
        # print(label_dict_n)

        assert len(label_dict_v) <= num_classes_v + 1
        assert len(label_dict_n) <= num_classes_n
        self.data_list = dict_db
        self.label_dict_v = label_dict_v
        self.label_dict_n = label_dict_n

        # dataset specific attributes
        empty_label_ids_v = self.find_empty_cls(label_dict_v, num_classes_v)
        empty_label_ids_n = self.find_empty_cls(label_dict_n, num_classes_n)
        self.db_attributes = {
            'dataset_name': 'epic-kitchens-100',
            'tiou_thresholds': np.linspace(0.1, 0.5, 5),
            'empty_label_ids_v': empty_label_ids_v,
            'empty_label_ids_n': empty_label_ids_n
        }

    def find_empty_cls(self, label_dict, num_classes):
        # find categories with out a data sample
        if len(label_dict) == num_classes:
            return []
        empty_label_ids = []
        label_ids = [v for _, v in label_dict.items()]
        for id in range(num_classes):
            if id not in label_ids:
                empty_label_ids.append(id)
        return empty_label_ids

    def get_attributes(self):
        return self.db_attributes

    def _load_json_db(self, json_file):
        # load database and select the subset
        with open(json_file, 'r') as fid:
            json_data = json.load(fid)
        json_db = json_data['database']

        # if label_dict is not available
        if self.label_dict_v is None and self.label_dict_n is None:
            #print('-------------------------------------')
            label_dict_v = {}
            label_dict_n = {}
            for key, value in json_db.items():
                for act in value['annotations']:
                    # if act['label'] == '-1':
                    #     print(act)
                    #     print(value['subset'])
                    label_dict_v[act['label']] = act['label_id']
                    label_dict_n[act['label_noun']] = act['label_id_noun']

        # fill in the db (immutable afterwards)
        dict_db = tuple()
        for key, value in json_db.items():
            # skip the video if not in the split
            if value['subset'].lower() not in self.split:
                continue

            # get fps if available
            if self.default_fps is not None:
                fps = self.default_fps
            elif 'fps' in value:
                fps = value['fps']
            else:
                assert False, "Unknown video FPS."

            # get video duration if available
            if 'duration' in value:
                duration = value['duration']
            else:
                duration = 1e8

            # get annotations if available
            if ('annotations' in value) and (len(value['annotations']) > 0):
                num_acts = len(value['annotations'])
                segments = np.zeros([num_acts, 2], dtype=np.float32)
                labels_v = np.zeros([num_acts, ], dtype=np.int64)
                labels_n = np.zeros([num_acts, ], dtype=np.int64)
                for idx, act in enumerate(value['annotations']):
                    segments[idx][0] = act['segment'][0]
                    segments[idx][1] = act['segment'][1]
                    labels_v[idx] = label_dict_v[act['label']]
                    labels_n[idx] = label_dict_n[act['label_noun']]
            else:
                segments = None
                labels = None
            dict_db += ({'id': key,
                         'fps' : fps,
                         'duration' : duration,
                         'segments' : segments,
                         'labels_v' : labels_v,
                         'labels_n' : labels_n
            }, )

        return dict_db, label_dict_v, label_dict_n

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, idx):
        # directly return a (truncated) data point (so it is very fast!)
        # auto batching will be disabled in the subsequent dataloader
        # instead the model will need to decide how to batch / preporcess the data
        video_item = self.data_list[idx]

        # load features
        filename_v = os.path.join(self.feat_folder_v,
                                self.file_prefix + video_item['id'] + self.file_ext_v)
        filename_a = os.path.join(self.feat_folder_a,
                                self.file_prefix + video_item['id'] + self.file_ext_a)


        with np.load(filename_v) as data_v:
            feats_v = data_v['feats'].astype(np.float32)

        feats_a = np.load(filename_a).astype(np.float32)
        # print('-----------------------------shape')
        # print(feats_v.shape)
        # print(feats_a.shape)

        #feat contact
        if feats_v.shape[0] - feats_a.shape[0] > 0:
            feats_a =np.pad(feats_a,((0,1),(0,0)),'edge')
        elif feats_v.shape[0] - feats_a.shape[0] < 0:
            feats_a = feats_a[:feats_v.shape[0],:]
        # print(feats_v.shape)
        # print(feats_a.shape)
            #feats_v =np.pad(feats_v,((0,1),(0,0)),'edge')
        # feats = np.concatenate((feats_v, feats_a), axis=1)

        # deal with downsampling (= increased feat stride)
        ####################### visual #####################
        feats_v = feats_v[::self.downsample_rate, :]
        feat_stride = self.feat_stride * self.downsample_rate
        # T x C -> C x T
        feats_v = torch.from_numpy(np.ascontiguousarray(feats_v.transpose()))

        ####################### audio ####################
        feats_a = feats_a[::self.downsample_rate, :]
        feat_stride = self.feat_stride * self.downsample_rate
        # T x C -> C x T
        feats_a = torch.from_numpy(np.ascontiguousarray(feats_a.transpose()))


        # convert time stamp (in second) into temporal feature grids
        # ok to have small negative values here
        if video_item['segments'] is not None:
            segments = torch.from_numpy(
                (video_item['segments'] * video_item['fps']- 0.5 * self.num_frames) / feat_stride
            )
            labels_v = torch.from_numpy(video_item['labels_v'])
            labels_n = torch.from_numpy(video_item['labels_n'])
        else:
            segments, labels = None, None

        # return a data dict
        data_dict = {'video_id'        : video_item['id'],
                     'feats_v'           : feats_v,      # C x T
                     'feats_a'           : feats_a,      # C x T
                     'segments'        : segments,   # N x 2
                     'labels_v'          : labels_v,     # N
                     'labels_n'          : labels_n,     # N
                     'fps'             : video_item['fps'],
                     'duration'        : video_item['duration'],
                     'feat_stride'     : feat_stride,
                     'feat_num_frames' : self.num_frames}

        # truncate the features during training
        if self.is_training and (segments is not None):
            #print('+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++==')
            #print(data_dict['video_id'])
            #print(idx)        
            data_dict = truncate_feats(
                data_dict, self.max_seq_len, self.trunc_thresh, self.seed, self.crop_ratio
            )

        # print('+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++==')
        # print(data_dict['video_id'])
        # print(len(data_dict['labels_v']))
        # print(len(data_dict['feats_v']))
        #print(data_dict['labels_v'])

        return data_dict