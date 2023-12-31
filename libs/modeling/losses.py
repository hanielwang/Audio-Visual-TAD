import torch
from torch.nn import functional as F
from matplotlib import pyplot
import matplotlib.pyplot as plt
from matplotlib.pyplot import MultipleLocator
def sigmoid_focal_loss(
    inputs,
    targets,
    reduction = 'none',
    alpha = 0.25,
    gamma = 2.0):
    """
    Loss used in RetinaNet for dense detection: https://arxiv.org/abs/1708.02002.
    Taken from
    https://github.com/facebookresearch/fvcore/blob/master/fvcore/nn/focal_loss.py
    # Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.

    Args:
        inputs: A float tensor of arbitrary shape.
                The predictions for each example.
        targets: A float tensor with the same shape as inputs. Stores the binary
                 classification label for each element in inputs
                (0 for the negative class and 1 for the positive class).
        alpha: (optional) Weighting factor in range (0,1) to balance
                positive vs negative examples. Default = 0.25 (no weighting).
        gamma: Exponent of the modulating factor (1 - p_t) to
               balance easy vs hard examples.
        reduction: 'none' | 'mean' | 'sum'
                 'none': No reduction will be applied to the output.
                 'mean': The output will be averaged.
                 'sum': The output will be summed.
    Returns:
        Loss tensor with the reduction option applied.
    """
    p = torch.sigmoid(inputs)
    ce_loss = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")
    p_t = p * targets + (1 - p) * (1 - targets)
    loss = ce_loss * ((1 - p_t) ** gamma)

    if alpha >= 0:
        alpha_t = alpha * targets + (1 - alpha) * (1 - targets)
        loss = alpha_t * loss
    # print('----------------------------------------------')
    # print(loss.sum())
    # print(loss.shape)
    if reduction == "mean":
        loss = loss.mean()
    elif reduction == "sum":
        loss = loss.sum()

    return loss


def ctr_giou_loss_1d(
    args,vid_idx,input_offsets, input_conf, input_actionness,
    target_offsets, target_start, target_end, target_action,
    reduction = 'none',
    eps = 1e-8
):
    """
    Generalized Intersection over Union Loss (Hamid Rezatofighi et. al)
    https://arxiv.org/abs/1902.09630

    This is an implementation that assumes a 1D event is represented using
    the same center point with different offsets, e.g.,
    (t1, t2) = (c - o_1, c + o_2) with o_i >= 0

    Reference code from
    https://github.com/facebookresearch/fvcore/blob/master/fvcore/nn/giou_loss.py

    Args:
        input/target_offsets (Tensor): 1D offsets of size (N, 2)
        reduction: 'none' | 'mean' | 'sum'
                 'none': No reduction will be applied to the output.
                 'mean': The output will be averaged.
                 'sum': The output will be summed.
        eps (float): small number to prevent division by zero
    """
    # check all 1D events are valid
    assert (input_offsets >= 0.0).all(), "predicted offsets must be non-negative"
    assert (target_offsets >= 0.0).all(), "GT offsets must be non-negative"

    lp, rp = input_offsets[:, 0], input_offsets[:, 1]
    lg, rg = target_offsets[:, 0], target_offsets[:, 1]

    # intersection key points
    lkis = torch.min(lp, lg)
    rkis = torch.min(rp, rg)

    # iou
    intsctk = rkis + lkis
    unionk = (lp + rp) + (lg + rg) - intsctk
    iouk = intsctk / unionk.clamp(min=eps)

    # smallest enclosing box
    lc = torch.max(lp, lg)
    rc = torch.max(rp, rg)

    # giou
    len_c = lc + rc
    miouk = iouk - ((len_c - unionk) / len_c.clamp(min=eps))

    loss_offset = 1.0 - miouk
    if reduction == "mean":
        loss_offset = loss_offset.mean() if loss_offset.numel() > 0 else 0.0 * loss_offset.sum()
    elif reduction == "sum":
        loss_offset = loss_offset.sum()

    

    ############################# Gaussian lable #################################
    sigma2 = args.gau_sigma#*3

    input_conf_s = torch.exp(torch.div(-torch.square(input_conf[:, 0]),2*sigma2*sigma2))
    input_conf_e = torch.exp(torch.div(-torch.square(input_conf[:, 1]),2*sigma2*sigma2))


    iou_mask = (miouk > 0.5).float()#iou_mask = (miouk > 0.7).float()
    loss_conf_s = torch.square(target_start.cuda() - input_conf_s).float()
    loss_conf_s = torch.sum(loss_conf_s * iou_mask).float()

    loss_conf_e = torch.square(target_end.cuda() - input_conf_e).float()
    loss_conf_e = torch.sum(loss_conf_e * iou_mask).float()
    
    loss_conf = 0.5*loss_conf_s + 0.5*loss_conf_e




    ############################ Actionness Loss #################################
    #iou_mask = (miouk > 0.5).float()#iou_mask = (miouk > 0.7).float()

    input_actionness = torch.sigmoid(input_actionness)
    # print('111111111111111111111111111111111111')
    # print(target_action[0:100])
    # # print(len(target_action[0]))
    # print(input_actionness[0:100])
    # print(len(input_actionness[0]))

    loss_action = torch.square(target_action.cuda() - input_actionness).float()
    #loss_action = torch.mean(loss_action).float()
    loss_action = torch.mean(loss_action * iou_mask).float()
    ###############################################################################

    loss = args.sigma1*loss_offset + args.loss_weight_boundary_conf*loss_conf# + 0.05*loss_action

    # print('========================================')
    # print(loss_offset)
    # print(loss_conf)
    # print(loss_action)

    # ############################################# plot curve ################################################
    # x = range(len(target_start))
    # plt.figure(figsize=(20,5))

    # plt.subplot(2,1,1)
    # plt.plot(x, target_start.cpu().detach().numpy(), ms=10,label='GT')
    # plt.legend()

    # plt.subplot(2,1,2)
    # plt.plot(x, input_conf_s.cpu().detach().numpy(), ms=10,label='Pred_start')
    # plt.legend()

    # # plt.subplot(3,1,3)
    # # plt.plot(x, input_conf_e.cpu().detach().numpy(), ms=10,label='Pred_end')

    # # plt.legend()

    # plt.xlabel('time')
    # plt.ylabel("value")
    # pyplot.yticks([0.0,1.2])
    # plt.savefig('./outputs/Training_BSN_GT_Gaussian_curve_combine1DCNN_'+str(vid_idx[0])+'_sigmoid.jpg', dpi = 80)
    # plt.clf()
    #############################################################################################################
    # ############################################# plot curve ################################################
    # x = range(len(target_start[0:200]))
    
    # fig = plt.figure(figsize=(20,5))
    # plt.subplot(4,1,1)
    # plt.plot(x, target_start.cpu().detach().numpy()[0:200], ms=10,label='GT_Start')
    # plt.legend()

    # plt.subplot(4,1,2)
    # plt.plot(x, input_conf_s.cpu().detach().numpy()[0:200], ms=10,label='Pred_Start')
    # plt.legend()

    # plt.subplot(4,1,3)
    # plt.plot(x, target_end.cpu().detach().numpy()[0:200], ms=10,label='GT_End')
    # plt.legend()

    # plt.subplot(4,1,4)
    # plt.plot(x, input_conf_e.cpu().detach().numpy()[0:200], ms=10,label='Pred_End')
    # plt.legend()

    # plt.xlabel('time')
    # plt.ylabel("confidence value")
    #   #pyplot.yticks([0.0,1.2])
    # fig.suptitle(str(vid_idx[0]))
    # plt.savefig('./outputs/Training_BSN_GT_Gaussian_curve_combine1DCNN_'+str(vid_idx)+'_sigmoid.jpg', dpi = 80)
    # plt.clf()
    # #############################################################################################################

    return loss, loss_action




    # # giou
    # len_c = lc + rc
    # miouk = iouk - ((len_c - unionk) / len_c.clamp(min=eps))

    # loss_offset = 1.0 - miouk
    # loss_conf = torch.square(miouk - input_conf.squeeze()).float()

    # print('--------------------------')
    # print(loss_offset[0:30])
    # print(loss_conf[0:30])
    # #loss = 1.0 - miouk
    # loss = loss_offset + loss_conf

    # if reduction == "mean":
    #     loss = loss.mean() if loss.numel() > 0 else 0.0 * loss.sum()
    # elif reduction == "sum":
    #     loss = loss.sum()

    # return loss
def binary_logistic_loss(scores,anchors):
    #p = torch.sigmoid(anchors)

    anchors = anchors.squeeze(-1)
    anchors = torch.sigmoid(anchors)

    anchors = torch.flatten(anchors,0)
    scores = torch.cat(scores,0)
    # print(anchors[:10])
    # print(scores[:10])
    # print('--------------------actioness_loss')
    # print(scores[:10])
    # print(anchors[:10])

    loss= torch.square(scores.cuda() - anchors).float()
    loss= torch.sum(loss).float()
    # print(len(anchors))
    # #print(len(scores[0]))
    # print(len(anchors[0]))
    # #print(len(scores[0][0]))
    # print(len(anchors[0][0]))
    #print(len(anchors[0][0][0]))




    # pmask=torch.can_cast(scores>0.5,dtype=torch.float32)
    # num_positive=torch.reduce_sum(pmask)
    # num_entries=torch.can_cast(torch.shape(scores)[0],dtype=torch.float32)    
    # ratio=num_entries/num_positive
    # coef_0=0.5*(ratio)/(ratio-1)
    # coef_1=coef_0*(ratio-1)
    
    # anchors=torch.reshape(anchors,[-1])
    # loss=coef_1*pmask*torch.log(anchors+0.00001)+coef_0*(1.0-pmask)*torch.log(1.0-anchors+0.00001)
    # loss=-torch.reduce_mean(loss)
    # num_sample=[torch.reduce_sum(pmask),ratio] 
    return loss#,num_sample