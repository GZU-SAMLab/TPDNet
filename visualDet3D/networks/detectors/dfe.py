import torch
import torch.nn as nn
import torch.nn.functional as F

class DepthAwareFE(nn.Module):
    def __init__(self, output_channel_num):
        super(DepthAwareFE, self).__init__()
        self.output_channel_num = output_channel_num
        self.depth_output = nn.Sequential(
            nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True),
            nn.Conv2d(self.output_channel_num, int(self.output_channel_num/2), 3, padding=1),
            nn.BatchNorm2d(int(self.output_channel_num/2)),
            nn.ReLU(),
            nn.Conv2d(int(self.output_channel_num/2), 96, 1),
        )
        self.depth_down = nn.Conv2d(96, 12, 3, stride=1, padding=1, groups=12)
        self.acf = dfe_module(256,256)
        self.hybrid_attention=HybridAttention(96,256)
        self.cn = nn.Conv2d(96,256, kernel_size=1, stride=1, padding=0)

    def forward(self, x):
        depth = self.depth_output(x)
        N, C, H, W = x.shape
        depth_guide = F.interpolate(depth, size=x.size()[2:], mode='bilinear', align_corners=False)
        #depth_enhance = self.cn(depth_guide)
        depth_enhance = self.hybrid_attention(depth_guide)
        depth_guide = self.depth_down(depth_guide)
        x = x + depth_enhance
        
        return depth, depth_guide, x

class dfe_module(nn.Module):

    def __init__(self, in_channels, out_channels):
        super(dfe_module, self).__init__()
        self.softmax = nn.Softmax(dim=-1)
        self.conv1 = nn.Sequential(nn.Conv2d(in_channels, out_channels, 1, bias=False),
                                nn.BatchNorm2d(out_channels),
                                nn.ReLU(True),
                                nn.Dropout2d(0.2, False))
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=1, stride=1, padding=0)

    def forward(self, feat_ffm, coarse_x):

        N, D, H, W = coarse_x.size()

        #depth prototype
        feat_ffm = self.conv1(feat_ffm)
        _, C, _, _ = feat_ffm.size()

        proj_query = coarse_x.view(N, D, -1)
        proj_key = feat_ffm.view(N, C, -1).permute(0, 2, 1)
        energy = torch.bmm(proj_query, proj_key)
        energy_new = torch.max(energy, -1, keepdim=True)[0].expand_as(energy) - energy
        attention = self.softmax(energy_new)

        #depth enhancement
        attention = attention.permute(0, 2, 1)
        proj_value = coarse_x.view(N, D, -1)
        out = torch.bmm(attention, proj_value)
        out = out.view(N, C, H, W)
        out = self.conv2(out)

        return out

class HybridAttention(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=7):
        super(HybridAttention, self).__init__()
        self.conv0=nn.Conv2d(in_channels, out_channels, 1, bias=False)
        # 通道注意力机制
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.max_pool = nn.AdaptiveMaxPool2d(1)
        self.fc1 = nn.Conv2d(out_channels, 128, 1, bias=False)
        self.relu1 = nn.ReLU()
        self.fc2 = nn.Conv2d(128, out_channels, 1, bias=False)
        self.sigmoid = nn.Sigmoid()
        
        # 空间注意力机制
        self.conv1 = nn.Conv2d(2, 1, kernel_size, padding=(kernel_size - 1) // 2, bias=False)
        self.sigmoid_spatial = nn.Sigmoid()

    def forward(self, x):
        x=self.conv0(x)
        # 通道注意力
        avg_out = self.fc2(self.relu1(self.fc1(self.avg_pool(x))))
        max_out = self.fc2(self.relu1(self.fc1(self.max_pool(x))))
        
        channel_out = self.sigmoid(avg_out + max_out) * x
        
        # 空间注意力
        avg_out = torch.mean(channel_out, dim=1, keepdim=True)
        max_out, _ = torch.max(channel_out, dim=1, keepdim=True)
        spatial_out = torch.cat([avg_out, max_out], dim=1)
        spatial_out = self.conv1(spatial_out)
        
        out = self.sigmoid_spatial(spatial_out) * channel_out
        return out
