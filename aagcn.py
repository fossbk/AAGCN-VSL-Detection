import math

import numpy as np
import torch
import torch.nn as nn
from torch.autograd import Variable
from graph import Graph
import pytorch_lightning as pl
from torchmetrics.classification import MulticlassAccuracy, BinaryAccuracy
import torch.optim as optim

def import_class(name):
    components = name.split('.')
    mod = __import__(components[0])
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod


def conv_branch_init(conv, branches):
    weight = conv.weight
    n = weight.size(0)
    k1 = weight.size(1)
    k2 = weight.size(2)
    nn.init.normal_(weight, 0, math.sqrt(2. / (n * k1 * k2 * branches)))
    nn.init.constant_(conv.bias, 0)


def conv_init(conv):
    nn.init.kaiming_normal_(conv.weight, mode='fan_out')
    nn.init.constant_(conv.bias, 0)


def bn_init(bn, scale):
    nn.init.constant_(bn.weight, scale)
    nn.init.constant_(bn.bias, 0)


class unit_tcn(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=9, stride=1):
        super(unit_tcn, self).__init__()
        pad = int((kernel_size - 1) / 2)
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=(kernel_size, 1), padding=(pad, 0),
                              stride=(stride, 1))

        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)
        conv_init(self.conv)
        bn_init(self.bn, 1)

    def forward(self, x):
        x = self.bn(self.conv(x))
        return x


class unit_gcn(nn.Module):
    def __init__(self, in_channels, out_channels, A, coff_embedding=4, num_subset=3, adaptive=True, attention=True):
        super(unit_gcn, self).__init__()
        inter_channels = out_channels // coff_embedding
        self.inter_c = inter_channels
        self.out_c = out_channels
        self.in_c = in_channels
        self.num_subset = num_subset
        num_jpts = A.shape[-1]

        self.conv_d = nn.ModuleList()
        for i in range(self.num_subset):
            self.conv_d.append(nn.Conv2d(in_channels, out_channels, 1))

        if adaptive:
            self.PA = nn.Parameter(torch.from_numpy(A.astype(np.float32)))
            self.alpha = nn.Parameter(torch.zeros(1))
            # self.beta = nn.Parameter(torch.ones(1))
            # nn.init.constant_(self.PA, 1e-6)
            # self.A = Variable(torch.from_numpy(A.astype(np.float32)), requires_grad=False)
            # self.A = self.PA
            self.conv_a = nn.ModuleList()
            self.conv_b = nn.ModuleList()
            for i in range(self.num_subset):
                self.conv_a.append(nn.Conv2d(in_channels, inter_channels, 1))
                self.conv_b.append(nn.Conv2d(in_channels, inter_channels, 1))
        else:
            self.A = Variable(torch.from_numpy(A.astype(np.float32)), requires_grad=False)
        self.adaptive = adaptive

        if attention:
            # self.beta = nn.Parameter(torch.zeros(1))
            # self.gamma = nn.Parameter(torch.zeros(1))
            # unified attention
            # self.Attention = nn.Parameter(torch.ones(num_jpts))

            # temporal attention
            self.conv_ta = nn.Conv1d(out_channels, 1, 9, padding=4)
            nn.init.constant_(self.conv_ta.weight, 0)
            nn.init.constant_(self.conv_ta.bias, 0)

            # s attention
            ker_jpt = num_jpts - 1 if not num_jpts % 2 else num_jpts
            pad = (ker_jpt - 1) // 2
            self.conv_sa = nn.Conv1d(out_channels, 1, ker_jpt, padding=pad)
            nn.init.xavier_normal_(self.conv_sa.weight)
            nn.init.constant_(self.conv_sa.bias, 0)

            # channel attention
            rr = 2
            self.fc1c = nn.Linear(out_channels, out_channels // rr)
            self.fc2c = nn.Linear(out_channels // rr, out_channels)
            nn.init.kaiming_normal_(self.fc1c.weight)
            nn.init.constant_(self.fc1c.bias, 0)
            nn.init.constant_(self.fc2c.weight, 0)
            nn.init.constant_(self.fc2c.bias, 0)

            # self.bn = nn.BatchNorm2d(out_channels)
            # bn_init(self.bn, 1)
        self.attention = attention

        if in_channels != out_channels:
            self.down = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 1),
                nn.BatchNorm2d(out_channels)
            )
        else:
            self.down = lambda x: x

        self.bn = nn.BatchNorm2d(out_channels)
        self.soft = nn.Softmax(-2)
        self.tan = nn.Tanh()
        self.sigmoid = nn.Sigmoid()
        self.relu = nn.ReLU(inplace=True)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                conv_init(m)
            elif isinstance(m, nn.BatchNorm2d):
                bn_init(m, 1)
        bn_init(self.bn, 1e-6)
        for i in range(self.num_subset):
            conv_branch_init(self.conv_d[i], self.num_subset)

    def forward(self, x):
        N, C, T, V = x.size()

        y = None
        if self.adaptive:
            A = self.PA
            # A = A + self.PA
            for i in range(self.num_subset):
                A1 = self.conv_a[i](x).permute(0, 3, 1, 2).contiguous().view(N, V, self.inter_c * T)
                A2 = self.conv_b[i](x).view(N, self.inter_c * T, V)
                A1 = self.tan(torch.matmul(A1, A2) / A1.size(-1))  # N V V
                A1 = A[i] + A1 * self.alpha
                A2 = x.view(N, C * T, V)
                z = self.conv_d[i](torch.matmul(A2, A1).view(N, C, T, V))
                y = z + y if y is not None else z
        else:
            A = self.A.cuda(x.get_device()) * self.mask
            for i in range(self.num_subset):
                A1 = A[i]
                A2 = x.view(N, C * T, V)
                z = self.conv_d[i](torch.matmul(A2, A1).view(N, C, T, V))
                y = z + y if y is not None else z

        y = self.bn(y)
        y += self.down(x)
        y = self.relu(y)

        if self.attention:
            # spatial attention
            se = y.mean(-2)  # N C V
            se1 = self.sigmoid(self.conv_sa(se))
            y = y * se1.unsqueeze(-2) + y
            # a1 = se1.unsqueeze(-2)

            # temporal attention
            se = y.mean(-1)
            se1 = self.sigmoid(self.conv_ta(se))
            y = y * se1.unsqueeze(-1) + y
            # a2 = se1.unsqueeze(-1)

            # channel attention
            se = y.mean(-1).mean(-1)
            se1 = self.relu(self.fc1c(se))
            se2 = self.sigmoid(self.fc2c(se1))
            y = y * se2.unsqueeze(-1).unsqueeze(-1) + y
            # a3 = se2.unsqueeze(-1).unsqueeze(-1)

            # unified attention
            # y = y * self.Attention + y
            # y = y + y * ((a2 + a3) / 2)
            # y = self.bn(y)
        return y


class TCN_GCN_unit(nn.Module):
    def __init__(self, in_channels, out_channels, A, stride=1, residual=True, adaptive=True, attention=True):
        super(TCN_GCN_unit, self).__init__()
        self.gcn1 = unit_gcn(in_channels, out_channels, A, adaptive=adaptive, attention=attention)
        self.tcn1 = unit_tcn(out_channels, out_channels, stride=stride)
        self.relu = nn.ReLU(inplace=True)
        # if attention:
        # self.alpha = nn.Parameter(torch.zeros(1))
        # self.beta = nn.Parameter(torch.ones(1))
        # temporal attention
        # self.conv_ta1 = nn.Conv1d(out_channels, out_channels//rt, 9, padding=4)
        # self.bn = nn.BatchNorm2d(out_channels)
        # bn_init(self.bn, 1)
        # self.conv_ta2 = nn.Conv1d(out_channels, 1, 9, padding=4)
        # nn.init.kaiming_normal_(self.conv_ta1.weight)
        # nn.init.constant_(self.conv_ta1.bias, 0)
        # nn.init.constant_(self.conv_ta2.weight, 0)
        # nn.init.constant_(self.conv_ta2.bias, 0)

        # rt = 4
        # self.inter_c = out_channels // rt
        # self.conv_ta1 = nn.Conv2d(out_channels, out_channels // rt, 1)
        # self.conv_ta2 = nn.Conv2d(out_channels, out_channels // rt, 1)
        # nn.init.constant_(self.conv_ta1.weight, 0)
        # nn.init.constant_(self.conv_ta1.bias, 0)
        # nn.init.constant_(self.conv_ta2.weight, 0)
        # nn.init.constant_(self.conv_ta2.bias, 0)
        # s attention
        # num_jpts = A.shape[-1]
        # ker_jpt = num_jpts - 1 if not num_jpts % 2 else num_jpts
        # pad = (ker_jpt - 1) // 2
        # self.conv_sa = nn.Conv1d(out_channels, 1, ker_jpt, padding=pad)
        # nn.init.constant_(self.conv_sa.weight, 0)
        # nn.init.constant_(self.conv_sa.bias, 0)

        # channel attention
        # rr = 16
        # self.fc1c = nn.Linear(out_channels, out_channels // rr)
        # self.fc2c = nn.Linear(out_channels // rr, out_channels)
        # nn.init.kaiming_normal_(self.fc1c.weight)
        # nn.init.constant_(self.fc1c.bias, 0)
        # nn.init.constant_(self.fc2c.weight, 0)
        # nn.init.constant_(self.fc2c.bias, 0)
        #
        # self.softmax = nn.Softmax(-2)
        # self.sigmoid = nn.Sigmoid()
        self.attention = attention

        if not residual:
            self.residual = lambda x: 0

        elif (in_channels == out_channels) and (stride == 1):
            self.residual = lambda x: x

        else:
            self.residual = unit_tcn(in_channels, out_channels, kernel_size=1, stride=stride)

    def forward(self, x):
        if self.attention:
            y = self.relu(self.tcn1(self.gcn1(x)) + self.residual(x))

            # spatial attention
            # se = y.mean(-2)  # N C V
            # se1 = self.sigmoid(self.conv_sa(se))
            # y = y * se1.unsqueeze(-2) + y
            # a1 = se1.unsqueeze(-2)

            # temporal attention
            # se = y.mean(-1)  # N C T
            # # se1 = self.relu(self.bn(self.conv_ta1(se)))
            # se2 = self.sigmoid(self.conv_ta2(se))
            # # y = y * se1.unsqueeze(-1) + y
            # a2 = se2.unsqueeze(-1)

            # se = y  # NCTV
            # N, C, T, V = y.shape
            # se1 = self.conv_ta1(se).permute(0, 2, 1, 3).contiguous().view(N, T, self.inter_c * V)  # NTCV
            # se2 = self.conv_ta2(se).permute(0, 1, 3, 2).contiguous().view(N, self.inter_c * V, T)  # NCVT
            # a2 = self.softmax(torch.matmul(se1, se2) / np.sqrt(se1.size(-1)))  # N T T
            # y = torch.matmul(y.permute(0, 1, 3, 2).contiguous().view(N, C * V, T), a2) \
            #         .view(N, C, V, T).permute(0, 1, 3, 2) * self.alpha + y

            # channel attention
            # se = y.mean(-1).mean(-1)
            # se1 = self.relu(self.fc1c(se))
            # se2 = self.sigmoid(self.fc2c(se1))
            # # y = y * se2.unsqueeze(-1).unsqueeze(-1) + y
            # a3 = se2.unsqueeze(-1).unsqueeze(-1)
            #
            # y = y * ((a2 + a3) / 2) + y
            # y = self.bn(y)
        else:
            y = self.relu(self.tcn1(self.gcn1(x)) + self.residual(x))
        return y


class Model(pl.LightningModule):
    def __init__(self, num_class=60, num_point=25, num_person=2, graph=None, graph_args=dict(), in_channels=3,
                 drop_out=0, adaptive=True, attention=True, learning_rate=1e-4, weight_decay=1e-4):
        super(Model, self).__init__()

        # if graph is None:
            # raise ValueError()
        # else:
            # Graph = import_class(graph)
        self.graph = Graph(**graph_args)

        A = self.graph.A
        self.num_class = num_class

        self.data_bn = nn.BatchNorm1d(num_person * in_channels * num_point)

        self.l1 = TCN_GCN_unit(in_channels, 64, A, residual=False, adaptive=adaptive, attention=attention)
        self.l2 = TCN_GCN_unit(64, 64, A, adaptive=adaptive, attention=attention)
        self.l3 = TCN_GCN_unit(64, 64, A, adaptive=adaptive, attention=attention)
        self.l4 = TCN_GCN_unit(64, 64, A, adaptive=adaptive, attention=attention)
        self.l5 = TCN_GCN_unit(64, 128, A, stride=2, adaptive=adaptive, attention=attention)
        self.l6 = TCN_GCN_unit(128, 128, A, adaptive=adaptive, attention=attention)
        self.l7 = TCN_GCN_unit(128, 128, A, adaptive=adaptive, attention=attention)
        self.l8 = TCN_GCN_unit(128, 256, A, stride=2, adaptive=adaptive, attention=attention)
        self.l9 = TCN_GCN_unit(256, 256, A, adaptive=adaptive, attention=attention)
        self.l10 = TCN_GCN_unit(256, 256, A, adaptive=adaptive, attention=attention)
        # self.l11 = TCN_GCN_unit(256, 512, A, stride=2, adaptive=adaptive, attention=attention)
        # self.l12 = TCN_GCN_unit(512, 512, A, adaptive=adaptive, attention=attention)
        # self.l13 = TCN_GCN_unit(512, 512, A, adaptive=adaptive, attention=attention)

        self.fc = nn.Linear(256, num_class)
        nn.init.normal_(self.fc.weight, 0, math.sqrt(2. / num_class))
        bn_init(self.data_bn, 1)
        if drop_out:
            self.drop_out = nn.Dropout(drop_out)
        else:
            self.drop_out = lambda x: x
        
        self.loss = nn.CrossEntropyLoss()
        self.metric = MulticlassAccuracy(num_class)
        # self.metric = BinaryAccuracy()
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.validation_step_loss_outputs = []
        self.validation_step_acc_outputs = []

        self.save_hyperparameters()

    def forward(self, x):
        N, C, T, V, M = x.size()

        x = x.permute(0, 4, 3, 1, 2).contiguous().view(N, M * V * C, T)
        x = self.data_bn(x.float())
        x = x.view(N, M, V, C, T).permute(0, 1, 3, 4, 2).contiguous().view(N * M, C, T, V)

        x = self.l1(x)
        x = self.l2(x)
        x = self.l3(x)
        x = self.l4(x)
        x = self.l5(x)
        x = self.l6(x)
        x = self.l7(x)
        x = self.l8(x)
        x = self.l9(x)
        x = self.l10(x)
        # x = self.l11(x)
        # x = self.l12(x)
        # x = self.l13(x)

        # N*M,C,T,V
        c_new = x.size(1)
        x = x.view(N, M, c_new, -1)
        x = x.mean(3).mean(1)
        x = self.drop_out(x)

        return self.fc(x)

    def training_step(self, batch, batch_idx):
        inputs, targets = batch
        outputs = self(inputs)
        y_pred_class = torch.argmax(torch.softmax(outputs, dim=1), dim=1)
        # print("Targets : ", targets)
        # print("Preds : ", y_pred_class) 
        train_accuracy = self.metric(y_pred_class, targets)
        loss = self.loss(outputs, targets)
        self.log('train_accuracy', train_accuracy, prog_bar=True, on_epoch=True)
        self.log('train_loss', loss, prog_bar=True, on_epoch=True)
        # return {"loss": loss, "train_accuracy" : train_accuracy}
        return loss
    
    def validation_step(self, batch, batch_idx):
        inputs, targets = batch
        outputs = self.forward(inputs)
        y_pred_class = torch.argmax(torch.softmax(outputs, dim=1), dim=1)
        valid_accuracy = self.metric(y_pred_class, targets)
        loss = self.loss(outputs, targets)
        self.log('valid_accuracy', valid_accuracy, prog_bar=True, on_epoch=True)
        self.log('valid_loss', loss, prog_bar=True, on_epoch=True)
        self.validation_step_loss_outputs.append(loss)
        self.validation_step_acc_outputs.append(valid_accuracy)
        return {"valid_loss" : loss, "valid_accuracy" : valid_accuracy}
    
    def on_validation_epoch_end(self):
        # avg_loss = torch.stack(
            # [x["valid_loss"] for x in outputs]).mean()
        # avg_acc = torch.stack(
            # [x["valid_accuracy"] for x in outputs]).mean()
        avg_loss = torch.stack(self.validation_step_loss_outputs).mean()
        avg_acc = torch.stack(self.validation_step_acc_outputs).mean()
        self.log("ptl/val_loss", avg_loss)
        self.log("ptl/val_accuracy", avg_acc)
        self.validation_step_loss_outputs.clear() 
        self.validation_step_acc_outputs.clear()

    def test_step(self, batch, batch_idx):
        inputs, targets = batch
        outputs = self.forward(inputs)
        y_pred_class = torch.argmax(torch.softmax(outputs, dim=1), dim=1)
        print("Targets : ", targets)
        print("Preds : ", y_pred_class)
        test_accuracy = self.metric(y_pred_class, targets)
        loss = self.loss(outputs, targets)
        self.log('test_accuracy', test_accuracy, prog_bar=True, on_epoch=True)
        self.log('test_loss', loss, prog_bar=True, on_epoch=True)
        return {"test_loss" : loss, "test_accuracy" : test_accuracy}

    def configure_optimizers(self):
        params = self.parameters()
        optimizer = optim.Adam(params=params, lr = self.learning_rate, weight_decay = self.weight_decay)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max')
        return {"optimizer": optimizer, 
                "lr_scheduler": {"scheduler": scheduler, "monitor": "valid_accuracy"}
               }
        # return optimizer  

    def predict_step(self, batch, batch_idx):
        return self(batch)

if __name__ == "__main__":  
    import os
    from torchinfo import summary
    print(os.getcwd())  
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = Model(num_class=20, num_point=18, num_person=1, 
                  graph_args={}, in_channels=2).to(device)
    # print(model.device)
    # N, C, T, V, M
    summary(model)
    x = torch.randn((1, 2, 80, 18, 1)).to(device)
    y = model(x)    
    print(y.shape)