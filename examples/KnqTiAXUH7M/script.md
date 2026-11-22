# Script — How to reverse engineer any editing style (Turned it into a skill)

Source: https://www.youtube.com/watch?v=KnqTiAXUH7M


## [0:00] They wait at the water's edge perfectly still.

`0:00` They wait at the water's edge perfectly  
`0:02` still. Then they burst out the  
`0:04` water faster than you could ever react.  
`0:07` >> I just built  
`0:08` for videos. You can now reverse engineer  
`0:10` any video you want. The clip you saw was  
`0:13` made with AI, and I put the entire thing  
`0:15` in a singular skill for free. It pulled  
`0:18` out all the cuts, all the colors,  
`0:20` pacing, even the way things move on  
`0:22` screen. Now, if you're new to it stands  
`0:25` for reverse engineer anything. It's a  
`0:27` repo on GitHub with over 400,000 stars,  
`0:30` and the entire point of it is that you  
`0:32` can point it any software you want, and  
`0:34` it'll take it apart so you can  
`0:36` reconstruct it. But if you were to give  
`0:38` it a video file, it wouldn't know what  
`0:40` to do with it. So I took its method and  
`0:42` I built it for video.  

## [0:44] So what does this skill actually do?

`0:44` So what does this skill actually do?  
`0:46` Well, the way it works is you give it  
`0:48` any video, it'll measure, like I said,  
`0:50` the cuts, the colors, the words, etc.  
`0:52` It'll then read the frames then it shows  
`0:53` you how the video was essentially put  
`0:55` together. Then it rebuilds that style  
`0:57` and checks the rebuild against the  
`0:58` original.  
`1:00` At the end of this video, you'll be able  
`1:01` to reverse engineer any video you want.  
`1:04` So here's the plan. First, I'll show you  
`1:05` how this works, then we'll test it on a  
`1:07` video where I already know the answer,  
`1:09` and lastly, we'll set it up together.  
`1:11` And if you've never done anything like  
`1:12` this, that's completely fine. You can do  
`1:14` all of this by just talking to Claude.  
`1:16` The most important part, which is the  
`1:17` skill, is actually free. It'll be the  

## [1:19] first thing in the description.

`1:19` first thing in the description. If you  
`1:20` get stuck, just jump in there and ask me  
`1:22` and I will try to help you out.  
`1:25` So the question becomes, well, why would  
`1:27` you even want this? Well, part of my  
`1:28` job, day to day, is working out how  
`1:30` somebody made a video. And a finished  
`1:32` video is like a locked box. You can see  
`1:34` the result, but you can never truly get  
`1:37` the product file.  
`1:38` REA a while back went viral because it  
`1:40` opens that box up for software. You see  
`1:42` a feature you like and your agent works  
`1:44` out how it's built with evidence. So I  
`1:47` wanted that same thing but for a video.  

## [1:49] Now, here's the thing.

`1:49` Now, here's the thing.  
`1:50` How does Claude even watch a video?  
`1:53` Well, the trick is that it doesn't.  
`1:56` Claude can read pictures, but it cannot  
`1:57` play a video file. So there's a free  
`1:59` tool called  
`2:00` that essentially breaks the video down  
`2:02` for it. Number one, it'll find every cut  
`2:04` by checking how much of the picture  
`2:06` changes from one frame to the next.  
`2:08` Number two, it'll actually pull those  
`2:09` frames out so Claude can read the type,  
`2:12` the layout, and the motion. Then number  
`2:14` three, it'll write down every word and  
`2:16` how fast they're spoken. Number four, it  
`2:18` measures the sound. Number five, colors.  
`2:21` And here's the part that I stole from  
`2:22` REA. It'll even show you the evidence  
`2:24` for every answer and it tells you what  
`2:26` it doesn't know.  

## [2:27] So, every finding gets one of three labels.

`2:27` So, every finding gets one of three  
`2:30` labels. Seen means it's measured and you  
`2:32` get a number timestamp.  
`2:34` Inferred means it's a reasonable guess  
`2:36` and it tells you why. An unknown just  
`2:38` means the file can't tell you what  
`2:40` software is was used to make a specific  
`2:42` video. We don't know.  
`2:43` I tested on one of my own videos because  
`2:45` I have the actual timeline and then I  
`2:46` tuned it on how the chapters and then  
`2:49` scored the half it hadn't seen.  
`2:51` It found 82% of the cuts. It caught  
`2:54` every single punch in  
`2:55` and it missed the jump cuts because  
`2:57` almost nothing changes in the pictures.  

## [2:59] So, I would treat the cut count as a minimum.

`2:59` So, I would treat the cut count as a  
`3:01` minimum.  
`3:01` And then it also read my fonts from the  
`3:03` frames alone.  
`3:05` All right.  
`3:06` On that note, let's actually build our  
`3:07` own version together.  
`3:09` Step one is to install the free tools.  
`3:11` It's one line and it's on the screen.  
`3:12` Step two is to put the skills in your  
`3:14` Claude skills folder.  
`3:16` And then step three is you're going to  
`3:18` want to run the health check. When it  
`3:19` says ready, you're completely good.  
`3:21` And it may ask you by the way while  
`3:22` you're doing this for a download of a  
`3:24` speech model, that's completely normal.  
`3:27` It should be around half a gigabyte.  
`3:28` It's only one time. So, if it asks you  
`3:30` to do that, just let it go through. Step  
`3:31` four is to pick your video, give it a  
`3:33` link or a file that you already have.  
`3:35` Pick a short section first because 30  
`3:37` seconds of video measures in about 6  
`3:39` seconds. And then step five,  
`3:41` tell Claude reverse engineer this video  
`3:43` with the reverse any video skill.  
`3:46` You'll get the evidence report as well  
`3:48` as the style file.  
`3:49` And then step six, ask it to rebuild  
`3:51` that style on your own topic.  

## [3:54] Finally, step seven, you can run the compare, fix the gaps, and then watch it all yourself…

`3:54` Finally, step seven, you can run the  
`3:56` compare, fix the gaps, and then watch it  
`3:58` all yourself.  
`4:00` Now, this is obviously super cool, but  
`4:02` there's a few things that this thing  
`4:03` cannot do. For example, it can't see  
`4:05` project files, layers, or effects sync.  
`4:08` It also can't tell you the exact font  
`4:09` names, only what it looks likes.  
`4:12` And sound effects are particularly weak  
`4:14` because Claude cannot hear audio. So I  
`4:17` would double check those.  

## [4:19] Now, can you do this with somebody else's video, somebody see on YouTube?

`4:19` Now, can you do this with somebody  
`4:21` else's video, somebody see on YouTube?  
`4:22` Absolutely, but I would use it to study  
`4:24` the style and then make your own video  
`4:26` with your own material.  
`4:28` The rules depend on where you live, so  
`4:29` obviously check them before to make sure  
`4:31` that you know what you're doing.  
`4:32` And the tools cost nothing on top of my  
`4:34` Claude plan.  
`4:35` So we took a locked box and we measured  
`4:37` everything we could.  
`4:39` The skill's free. It'll be the first  
`4:40` thing in the description. Thank you so  
`4:42` much for watching. If you appreciated  
`4:43` this or if there's something that you  
`4:44` learned from it, subscribe because I'm  
`4:46` trying to make as many of these videos  
`4:47` as possible and you subscribing tells me  
`4:48` that you want more of this type of  
`4:50` content.  
`4:51` What video should I do next? Let me know  
`4:53` in the comments. Otherwise, thank you  
`4:54` for watching. And if you want to make  
`4:56` Netflix style documentaries, click this  
`4:58` link right here.  
