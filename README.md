# Audio-Visual Temporal Action Detection

This repository implements the boundaries head proposed in the paper:

Hanyuan Wang, Majid Mirmehdi, Dima Damen, Toby Perrett, **Centre Stage: Centricity-based Audio-Visual Temporal Action Detection**, 2023


This repository is based on [ActionFormer](https://github.com/happyharrycn/actionformer_release).



## Citing

When using this code, kindly reference:

```
@INPROCEEDINGS{Hanaudiovisual,
  author={Wang, Hanyuan and Mirmehdi, Majid and Damen, Dima and Perrett, Toby}
  booktitle={The 1st Workshop in Video Understanding and its Applications (VUA 2023)},
  title={Centre Stage: Centricity-based Audio-Visual Temporal Action Detection},
  year={2023}}
```

## Dependencies

* Python 3.5+
* PyTorch 1.11
* CUDA 11.0+
* GCC 4.9+
* TensorBoard
* NumPy 1.11+
* PyYaml
* Pandas
* h5py
* joblib

Complie NMS code by: 
```
cd ./libs/utils
python setup.py install --user
cd ../..
```


## Preparation

### Datasets and feature

You can download the annotation repository of EPIC-KITCHENS-100 at [here](https://github.com/epic-kitchens/epic-kitchens-100-annotations). Place it into a folder: ./data/visual_feature/epic_kitchens/annotations.

You can download the videos of EPIC-KITCHENS-100 at [here](https://github.com/epic-kitchens/epic-kitchens-download-scripts).

You can download the visual feature on EPIC-KITCHENS-100 at [here](https://uob-my.sharepoint.com/:u:/g/personal/dm19329_bristol_ac_uk/EeXBKfXuurxNiZ3wazARQQsBD7j76jQMknSTgUTmXFYOog?e=Nt10i2). Place it into a folder: ./data/visual_feature/epic_kitchens/features.

You can extract the audio feature on EPIC-KITCHENS-100 follow this repository [here](https://github.com/ekazakos/auditory-slow-fast). Place extracted features into a folder: ./data/audio_feature/extracted_features_retrain_small_win.

If everything goes well, you can get the folder architecture of ./data like this:

    data 
    ├── audio_feature
    ├         └── extracted_features_retrain_small_win              
    └── visual_feature
              └── epic_kitchens                    
                     ├── features              
                     └── annotations



### Pretrained models

You can download our pretrained models on EPIC-KITCHENS-100 at [here](https://uob-my.sharepoint.com/:u:/g/personal/dm19329_bristol_ac_uk/ETHbaJ3cuHRFv3pzhyZCqZAB35eZN4vnsDWJlY7S_HbCJQ?e=spq8pn).



## Training/validation on EPIC-KITCHENS-100
To train the model run:
```
python ./train.py ./configs/epic_slowfast.yaml --output reproduce  --loss_act_weight 1.7  --cen_gau_sigma 1.7 --loss_weight_boundary_conf 0.5 

```
To validate the model run:
```
python ./eval.py ./configs/epic_slowfast.yaml ./ckpt/epic_slowfast_reproduce/name_of_the_best_model 
```

## Results
```
[RESULTS] Action detection results_self.ap_action

|tIoU = 0.10: mAP = 20.88 (%)
|tIoU = 0.20: mAP = 20.13 (%)
|tIoU = 0.30: mAP = 18.92 (%)
|tIoU = 0.40: mAP = 17.51 (%)
|tIoU = 0.50: mAP = 15.03 (%)
Avearge mAP: 18.50 (%)
[RESULTS] Action detection results_self.ap_noun

|tIoU = 0.10: mAP = 26.78 (%)
|tIoU = 0.20: mAP = 25.58 (%)
|tIoU = 0.30: mAP = 23.91 (%)
|tIoU = 0.40: mAP = 21.45 (%)
|tIoU = 0.50: mAP = 17.68 (%)
Avearge mAP: 23.08 (%)
[RESULTS] Action detection results_self.ap_verb

|tIoU = 0.10: mAP = 24.11 (%)
|tIoU = 0.20: mAP = 23.00 (%)
|tIoU = 0.30: mAP = 21.66 (%)
|tIoU = 0.40: mAP = 20.16 (%)
|tIoU = 0.50: mAP = 16.57 (%)
Avearge mAP: 21.10 (%)
```

## Reference

This implementation is based on [ActionFormer](https://github.com/happyharrycn/actionformer_release).
