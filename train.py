# python imports
import argparse
import os
import time
import datetime
from pprint import pprint
import random
# torch imports
import torch
import torch.nn as nn
import torch.utils.data
import numpy as np
# for visualization
#from torch.utils.tensorboard import SummaryWriter

# our code
from libs.core import load_config
from libs.datasets import make_dataset, make_data_loader
from libs.modeling import make_meta_arch
from libs.utils import (train_one_epoch, valid_one_epoch, ANETdetection,
                        save_checkpoint, make_optimizer, make_scheduler,
                        fix_random_seed, ModelEma)


################################################################################
def main(args):
    """main function that handles training / inference"""

    """1. setup parameters / folders"""
    # parse args
    args.start_epoch = 0
    if os.path.isfile(args.config):
        cfg = load_config(args.config)
    else:
        raise ValueError("Config file does not exist.")
    pprint(cfg)

    # prep for output folder (based on time stamp)
    if not os.path.exists(cfg['output_folder']):
        os.mkdir(cfg['output_folder'])
    cfg_filename = os.path.basename(args.config).replace('.yaml', '')
    if len(args.output) == 0:
        ts = datetime.datetime.fromtimestamp(int(time.time()))
        ckpt_folder = os.path.join(
            cfg['output_folder'], cfg_filename + '_' + str(ts))
    else:
        ckpt_folder = os.path.join(
            cfg['output_folder'], cfg_filename + '_' + str(args.output))
    if not os.path.exists(ckpt_folder):
        os.mkdir(ckpt_folder)
    # tensorboard writer
    #tb_writer = SummaryWriter(os.path.join(ckpt_folder, 'logs'))

    # fix the random seeds (this will fix everything)
    rng_generator = fix_random_seed(args.training_seed, include_cuda=True)
    #rng_generator = fix_random_seed(cfg['init_rand_seed'], include_cuda=True)
    args.training_seed
    #rng_generator = random.seed(a=None, version=2)


    # re-scale learning rate / # workers based on number of GPUs
    cfg['opt']["learning_rate"] *= len(cfg['devices'])
    cfg['loader']['num_workers'] *= len(cfg['devices'])

    """2. create dataset / dataloader"""
    train_dataset = make_dataset(
        cfg['dataset_name'], True, cfg['train_split'], args.training_seed, **cfg['dataset']
        #cfg['dataset_name'], True, cfg['train_split'], cfg['init_rand_seed'], **cfg['dataset']
    )
    # update cfg based on dataset attributes (fix to epic-kitchens)
    train_db_vars = train_dataset.get_attributes()
    cfg['model']['train_cfg']['head_empty_cls_v'] = train_db_vars['empty_label_ids_v']
    cfg['model']['train_cfg']['head_empty_cls_n'] = train_db_vars['empty_label_ids_n']


    # data loaders
    train_loader = make_data_loader(
        train_dataset, True, rng_generator, **cfg['loader'])
    

    """3. create model, optimizer, and scheduler"""
    # model
    model = make_meta_arch(cfg['model_name'], **cfg['model'])
    # not ideal for multi GPU training, ok for now
    model = nn.DataParallel(model, device_ids=cfg['devices'])
    # optimizer
    optimizer = make_optimizer(model, cfg['opt'])
    # schedule
    num_iters_per_epoch = len(train_loader)
    scheduler = make_scheduler(optimizer, cfg['opt'], num_iters_per_epoch)

    # enable model EMA
    print("Using model EMA ...")
    model_ema = ModelEma(model)

    """4. Resume from model / Misc"""
    # resume from a checkpoint?
    if args.resume:
        if os.path.isfile(args.resume):
            # load ckpt, reset epoch / best rmse
            checkpoint = torch.load(args.resume,
                map_location = lambda storage, loc: storage.cuda(
                    cfg['devices'][0]))
            args.start_epoch = checkpoint['epoch'] + 1
            model.load_state_dict(checkpoint['state_dict'])
            model_ema.module.load_state_dict(checkpoint['state_dict_ema'])
            # also load the optimizer / scheduler if necessary
            optimizer.load_state_dict(checkpoint['optimizer'])
            scheduler.load_state_dict(checkpoint['scheduler'])
            print("=> loaded checkpoint '{:s}' (epoch {:d}".format(
                args.resume, checkpoint['epoch']
            ))
        else:
            print("=> no checkpoint found at '{}'".format(args.resume))
            return

    # save the current config
    with open(os.path.join(ckpt_folder, 'config.txt'), 'w') as fid:
        pprint(cfg, stream=fid)
        fid.flush()

    """4. training / validation loop"""
    print("\nStart training model {:s} ...".format(cfg['model_name']))

    # start training
    max_epochs = cfg['opt'].get(
        'early_stop_epochs',
        cfg['opt']['epochs'] + cfg['opt']['warmup_epochs']
    )

    for epoch in range(args.start_epoch, max_epochs):
        if epoch == args.stop_save_epoch:
            break
        # train for one epoch
        train_one_epoch(
            args,
            train_loader,
            model,
            optimizer,
            scheduler,
            epoch,
            model_ema = model_ema,
            clip_grad_l2norm = cfg['train_cfg']['clip_grad_l2norm'],
            tb_writer=None,
            print_freq=args.print_freq
        )

        # save ckpt once in a while
        if (
            (epoch == max_epochs - 1) or
            (
                (args.ckpt_freq > 0) and
                (epoch % args.ckpt_freq == 0) and
                (epoch > 15)
            )
        ):
            save_states = {
                'epoch': epoch,
                'state_dict': model.state_dict(),
                'scheduler': scheduler.state_dict(),
                'optimizer': optimizer.state_dict(),
            }

            save_states['state_dict_ema'] = model_ema.module.state_dict()
            save_checkpoint(
                save_states,
                False,
                file_folder=ckpt_folder,
                file_name='epoch_{:03d}.pth.tar'.format(epoch)
            )

    # wrap up
    #tb_writer.close()
    print("All done!")
    return


def save_rng_state(file_name1,file_name2):
    rng_state = torch.get_rng_state()
    torch.save(rng_state, file_name1)

    rng_state2 = torch.cuda.get_rng_state()
    torch.save(rng_state2, file_name2)
################################################################################
if __name__ == '__main__':
    """Entry Point"""
    # the arg parser
    parser = argparse.ArgumentParser(
      description='Train a point-based transformer for action localization')
    parser.add_argument('config', metavar='DIR',
                        help='path to a config file')
    parser.add_argument('-p', '--print-freq', default=10, type=int,
                        help='print frequency (default: 10 iterations)')
    parser.add_argument('-c', '--ckpt-freq', default=1, type=int,
                        help='checkpoint frequency (default: every 5 epochs)')
    parser.add_argument('--output', default='', type=str,
                        help='name of exp folder (default: none)')
    parser.add_argument('--resume', default='', type=str, metavar='PATH',
                        help='path to a checkpoint (default: none)')
    parser.add_argument('--gau_sigma', default=5.5, type=float,
                        help='ratio for combine total loss')
    parser.add_argument('--sigma1', default=0.5, type=float,
                        help='ratio for combine total loss')
    parser.add_argument('--sigma2', default=0.5, type=float,
                        help='ratio for combine total loss')
    parser.add_argument('--sigma3', default=0.5, type=float,
                        help='ratio for combine total loss')
    parser.add_argument('--noun_cls_weight', default=1.5, type=float,
                        help='ratio for combine total loss')
    parser.add_argument('--verb_cls_weight', default=1, type=float,
                        help='ratio for combine total loss')
    parser.add_argument('--training_seed', default=1234567891, type=int,
                        help='ratio for combine total loss')
    parser.add_argument('--stop_save_epoch', default=32, type=int)

    parser.add_argument('--cen_sigma', default=1, type=float,
                        help='ratio for combine total loss')
    parser.add_argument('--loss_a_weight', default=1, type=float,
                        help='ratio for audio loss')
    parser.add_argument('--loss_act_weight', default=1.5, type=float,
                        help='ratio for audio loss')

    parser.add_argument('--cen_gau_sigma', default=4, type=float,
                        help='parameter for generate centernness labels')

    parser.add_argument('--loss_weight_boundary_conf', default=1, type=float,
                        help='ratio for audio loss')
    args = parser.parse_args()

    ############################## print args #############################
    print('############################ User-defined parameter ############################')
    for k, v in sorted(vars(args).items()):
        print(k, ' = ', v)
    print('############################ User-defined parameter ############################')

    main(args)



