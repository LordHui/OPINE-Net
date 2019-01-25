import torch
import torch.nn as nn
import scipy.io as sio
import numpy as np
import os
import sys
import models
import dataset
from torch.utils.data import DataLoader
import platform
import utils
import option_multiple
import torch.optim.lr_scheduler as lr_scheduler


def train():
    args = option_multiple.get_args()
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu_list

    CS_ratio = args.cs_ratio.split(',')
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    cs_ratio_dic = {4: 43, 1: 10, 10: 109, 25: 272, 30: 327, 40: 436, 50: 545}

    n_input = [cs_ratio_dic[int(k)] for k in CS_ratio]
    n_output = 1089

    # our model
    model = models.get_ISTANet_Multiple(args.layer_num, n_input, args.share_flag)
    model.apply(utils.weights_init)

    model = nn.DataParallel(model)
    model = model.to(device)

    utils.print_paras_info(model)

    training_data = sio.loadmat(args.input_data)
    training_labels = training_data['labels']

    num_workers = 0 if (platform.system() == "Windows") else 4
    rand_loader = DataLoader(dataset=dataset.CustomizedDataset(training_labels, args.nrtrain), batch_size=args.batch_size, num_workers=num_workers,
                            shuffle=True)

    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    scheduler = lr_scheduler.StepLR(optimizer, step_size=200, gamma=0.1)

    model_dir = "OPINE_Net_Multiple_share_%d_phase_%d_group_%d_%s_Binary_Norm_%.2f_Single_%.4f" % (
        args.share_flag, args.layer_num, args.group_num, ''.join([k for k in CS_ratio]), args.phi_weight, args.learning_rate)

    output_file_name = "Log_output_%s.txt" % model_dir

    if not os.path.exists(model_dir):
        os.makedirs(model_dir)

    if args.start_epoch > 0:
        pre_model_dir = model_dir
        model.load_state_dict(torch.load('./%s/net_params_%d.pkl' % (pre_model_dir, args.start_epoch)))

    Eye_I = [torch.eye(k).to(device) for k in n_input]

    # Training loop
    for epoch_i in range(args.start_epoch + 1, args.end_epoch + 1):

        for param_group in optimizer.param_groups:
            lr_value_= param_group['lr']

        for data in rand_loader:
            batch_ys = data.to(device)

            phi_index = np.random.randint(0, len(n_input))

            [y_pred, y_layers_sym, Phi] = model(batch_ys, phi_index)

            # Compute and print loss
            loss = torch.mean(torch.pow(y_pred - batch_ys, 2))

            loss_sym = torch.mean(torch.pow(y_layers_sym[0], 2))
            for k in range(args.layer_num - 1):
                loss_sym += torch.mean(torch.pow(y_layers_sym[k + 1], 2))

            loss_phi = torch.mean(torch.pow(torch.mm(Phi, torch.transpose(Phi, 0, 1)) - Eye_I[phi_index], 2))

            # PhiTPhix = torch.mm(torch.mm(batch_ys, torch.transpose(Phi, 0, 1)), Phi)
            # loss_I = torch.mean(torch.pow(PhiTPhix - batch_ys, 2))

            loss_w1 = torch.Tensor([0.01]).to(device)
            loss_w2 = torch.Tensor([args.phi_weight]).to(device)
            # loss_w3 = torch.Tensor([0.01]).to(device)

            loss_all = loss + torch.mul(loss_w1, loss_sym) + torch.mul(loss_w2, loss_phi)
            # loss_all = loss + torch.mul(loss_w2, loss_phi)
            # loss_all = loss + torch.mul(loss_w1, loss_sym) + torch.mul(loss_w2, loss_phi) + torch.mul(loss_w3, loss_I)

            # Zero gradients, perform a backward pass, and update the weights.
            optimizer.zero_grad()
            loss_all.backward()
            optimizer.step()


            output_data = "[%02d/%02d] Loss: %.4f, Loss_sym: %.4f, Loss_phi: %.8f lr_value_: %.6f\n" % (
            epoch_i, args.end_epoch, loss.item(), loss_sym.item(), loss_phi.item(), lr_value_)
            # output_data = "[%02d/%02d] Loss: %.4f, Loss_sym: %.4f, Loss_phi: %.8f, Loss_I: %.4f\n" % (epoch_i, end_epoch, loss.item(), loss_sym.item(), loss_phi.item(), loss_I.item())
            print(output_data)

        scheduler.step()

        output_file = open(output_file_name, 'a')
        output_file.write(output_data)
        output_file.close()

        torch.save(model.state_dict(), "./%s/net_params_%d.pkl" % (model_dir, epoch_i))  # save only the parameters


if __name__ == '__main__':
    train()